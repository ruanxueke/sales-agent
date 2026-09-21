"""发布产物校验：版本、迁移头、安装包、哈希和可选数字签名。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def migration_head() -> str:
    heads: dict[str, str] = {}
    children: set[str] = set()
    for path in sorted((ROOT / "migrations" / "versions").glob("[0-9]*.py")):
        text = path.read_text(encoding="utf-8")
        revision = re.search(r'^revision\s*=\s*["\']([^"\']+)', text, re.M)
        down = re.search(r'^down_revision\s*=\s*(.+)$', text, re.M)
        if not revision:
            continue
        heads[revision.group(1)] = path.name
        if down:
            match = re.findall(r'["\']([^"\']+)["\']', down.group(1))
            if match:
                children.add(match[0])
    values = sorted(set(heads) - children)
    if len(values) != 1:
        raise SystemExit(f"迁移链不是单头: {values}")
    return values[0]


def verify_installer(path: Path, require_signed: bool) -> dict:
    if not path.exists():
        raise SystemExit(f"安装包不存在: {path}")
    status = "not_checked"
    if os.name == "nt":
        command = (
            "Get-AuthenticodeSignature -LiteralPath "
            + json.dumps(str(path))
            + " | Select-Object -ExpandProperty Status"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=60,
        )
        status = (result.stdout or "").strip() or "Unknown"
        if require_signed and status.lower() != "valid":
            raise SystemExit(f"安装包未签名或签名无效: {status}")
    elif require_signed:
        raise SystemExit("非 Windows 环境无法校验 Authenticode 签名")
    return {
        "path": str(path),
        "size": path.stat().st_size,
        "sha256": sha256(path),
        "signature": status,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--installer",
        default="",
    )
    parser.add_argument("--require-signed", action="store_true")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    package = read_json(ROOT / "desktop-client" / "package.json")
    main_source = (ROOT / "desktop-client" / "main.js").read_text(
        encoding="utf-8"
    )
    run_source = (ROOT / "wechat_bridge" / "run.py").read_text(
        encoding="utf-8"
    )
    desktop_agent = re.search(
        r"BRIDGE_AGENT_VERSION\s*=\s*['\"]([^'\"]+)",
        main_source,
    )
    bridge_agent = re.search(
        r'BRIDGE_AGENT_VERSION\s*=\s*"([^"]+)"',
        run_source,
    )
    if not desktop_agent or not bridge_agent:
        raise SystemExit("无法读取桥接版本")
    if desktop_agent.group(1) != bridge_agent.group(1):
        raise SystemExit("桌面端与桥接版本不一致")

    installer_path = Path(args.installer) if args.installer else None
    if installer_path is None:
        candidates = sorted(
            (ROOT / "desktop-client" / "dist").glob(
                "SalesAgentConsole Setup *.exe"
            ),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            raise SystemExit("未找到客户端安装包")
        installer_path = candidates[0]

    manifest = {
        "client_version": package.get("version"),
        "bridge_version": bridge_agent.group(1),
        "migration_head": migration_head(),
        "installer": verify_installer(
            installer_path,
            require_signed=args.require_signed,
        ),
    }
    text = json.dumps(manifest, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
