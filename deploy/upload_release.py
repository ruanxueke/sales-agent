#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把发布包推到云端服务器，并校验是否完整落盘。

为什么需要它
------------
本机（Windows）没有服务器的 SSH 私钥，服务器也没配免密登录，
`ssh root@127.0.0.1` 直接 Permission denied。但中台自带一条上传路由：

    POST /api/v1/knowledge/upload     （见 api/knowledge.py）
    落地目录 = settings.KNOWLEDGE_BASE_DIR
             = /opt/sales-agent/data/knowledge_base/<原文件名>
    鉴权     = X-API-Key: <ADMIN_API_KEYS 里的任意一个>

`data/` 与 `*.zip` 都在 .dockerignore 里，所以把发布包放在该目录下
**不会**在下次 `docker compose build` 时被 COPY 进镜像。

用法
----
    # 只上传
    python deploy/upload_release.py release/sales-agent-hardening-20260911.zip

    # 上传 + 校验（默认就校验）
    python deploy/upload_release.py release/xxx.zip --verify

    # 只校验某个已上传的包
    python deploy/upload_release.py release/xxx.zip --verify-only

上传只是把文件放到服务器上。真正生效还需要在服务器终端执行：

    cd /opt/sales-agent
    unzip -o data/knowledge_base/<包名>.zip -d /opt/sales-agent
    bash deploy/install_hardening_20260911.sh

这一步无法远程代跑：仓库里既没有 SSH 客户端（无 paramiko/asyncssh），
也没有任何执行 shell 的路由。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UPLOAD_URL = "http://127.0.0.1:5000/api/v1/knowledge/upload"
BASE = "http://127.0.0.1:5000"

# Key 的来源：优先 server.env（本机记录的生产配置），其次 .env
ENV_CANDIDATES = ("server.env", ".env")
KEY_NAMES = ("ADMIN_API_KEYS", "API_KEYS")


def load_key() -> str:
    """从本地 env 文件里取管理员 Key。不打印、不落盘。"""
    for fname in ENV_CANDIDATES:
        p = PROJECT_ROOT / fname
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for name in KEY_NAMES:
            m = re.search(rf"^{name}=(\S+)\s*$", text, re.M)
            if m:
                return m.group(1).split(",")[0].strip()
    raise SystemExit("!! 在 server.env / .env 里都找不到 ADMIN_API_KEYS 或 API_KEYS")


def mask(key: str) -> str:
    return f"{key[:6]}...{key[-4:]}" if len(key) > 12 else "******"


def upload(zip_path: Path, key: str) -> int:
    if not zip_path.is_file():
        print(f"!! 找不到发布包: {zip_path}")
        return 1
    size = zip_path.stat().st_size
    print(f"包    : {zip_path.name}")
    print(f"大小  : {size} 字节 ({size / 1024:.1f} KB)")
    print(f"目标  : {UPLOAD_URL}")
    print(f"Key   : {mask(key)}（脱敏）")
    print()

    with zip_path.open("rb") as f:
        files = {"file": (zip_path.name, f, "application/zip")}
        try:
            r = httpx.post(UPLOAD_URL, headers={"X-API-Key": key}, files=files,
                           timeout=httpx.Timeout(300.0, connect=20.0))
        except Exception as e:
            print(f"!! 上传失败（网络层）: {type(e).__name__}: {e}")
            return 1

    print(f"HTTP {r.status_code}")
    print(f"响应: {r.text[:500]}")
    if r.status_code >= 400:
        print()
        if r.status_code in (401, 403):
            print("   Key 不对，或服务器上的 ADMIN_API_KEYS 与本地 server.env 不一致。")
        elif r.status_code == 404:
            print("   服务器上跑的旧代码没有这条路由——先把中台升级上去。")
        return 1
    return 0


def verify(zip_path: Path, key: str) -> int:
    """核对 /knowledge/versions 里该文件的 size 是否与本地一致。

    服务器不会回传字节内容，只能比大小 + 版本记录是否写入成功。
    大小一致基本可断定上传完整（该接口是一次性 write_bytes，不会截断）。
    """
    local = zip_path.stat().st_size
    r = httpx.get(BASE + "/api/v1/knowledge/versions",
                  headers={"X-API-Key": key}, timeout=30)
    if r.status_code >= 400:
        print(f"!! 校验接口返回 {r.status_code}: {r.text[:200]}")
        return 1
    try:
        versions = r.json().get("versions", [])
    except Exception:
        print(f"!! 校验响应不是 JSON: {r.text[:200]}")
        return 1

    hit = [v for v in versions if v.get("filename") == zip_path.name]
    if not hit:
        print(f"!! 服务器版本表里没有 {zip_path.name}，上传可能没落盘")
        return 1

    v = max(hit, key=lambda x: x.get("id", 0))
    srv = v.get("size")
    print(f"服务器记录: id={v.get('id')}  name={v.get('filename')}  "
          f"size={srv}  hash={v.get('file_hash')}  status={v.get('status')}")
    if srv == local:
        print(f"大小校验: 一致（{local} 字节）")
        return 0
    print(f"!! 大小不一致：本地 {local}，服务器 {srv}")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="推送发布包到云端并校验")
    ap.add_argument("zip", help="发布包路径")
    ap.add_argument("--verify-only", action="store_true", help="只校验，不上传")
    ap.add_argument("--no-verify", action="store_true", help="只上传，不校验")
    args = ap.parse_args()

    zip_path = Path(args.zip)
    if not zip_path.is_absolute():
        zip_path = (PROJECT_ROOT / zip_path).resolve()

    key = load_key()
    if not args.verify_only:
        rc = upload(zip_path, key)
        if rc != 0:
            return rc
        print()

    if args.no_verify:
        return 0

    print("=== 校验 ===")
    rc = verify(zip_path, key)
    print()
    if rc == 0:
        print("上传完成。接下来在服务器终端执行：")
        print("  cd /opt/sales-agent")
        print(f"  unzip -o data/knowledge_base/{zip_path.name} -d /opt/sales-agent")
        print("  bash deploy/install_hardening_20260911.sh")
    return rc


if __name__ == "__main__":
    sys.exit(main())
