#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信信息抓取 (Windows) —— 让 AI 直接读取本机微信聊天记录。

设计原则：
  本脚本只负责「读懂并整理数据」，不负责「撬锁」。
  密钥提取与数据库解密交给专业的 wcdb-key-tool（MIT 开源，只读内存扫描）。

子命令:
  doctor     环境自检（微信版本 / 进程 / 数据目录 / 密钥 / 解密库）
  key        提取数据库密钥（需微信运行中）
  decrypt    解密数据库到本地
  sessions   列出最近会话
  locate K   按关键词定位群聊或联系人
  capture N  抓取指定会话的消息
  unread     汇总未读消息
  install    安装为 WorkBuddy 技能包
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------- 编码 / 常量

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DATA_DIR = Path(os.environ.get("WECHAT_CAPTURE_HOME", Path.home() / ".wechat-capture"))
KEYTOOL_URL_API = ("https://api.github.com/repos/TANGandXUE/wcdb-key-tool"
                   "/contents/wcdb_key_tool_windows.py")
KEYTOOL_NAME = "wcdb_key_tool_windows.py"

# 微信官方标注：4.0.3.36 以上旧工具失效；本方案支持到 4.1.x
VERSION_NOTE_OK = "4.1.x 运行时扫描已验证"

MSG_TYPE = {
    1: "文本", 3: "图片", 34: "语音", 42: "名片", 43: "视频", 47: "表情",
    48: "位置", 49: "分享", 50: "语音通话", 51: "视频通话", 10000: "系统",
}

NOISE_RE = re.compile(
    r"<sysmsg>.*?</sysmsg>|<msg>.*?</msg>|\[收到一条微信消息\]|"
    r"撤回了一条消息|加入了群聊|退出了群聊|邀请.*?加入了群聊|"
    r"你已添加了|现在可以开始聊天了|拍了拍|<?xml",
    re.S,
)


def _print(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- 环境探测

def find_accounts() -> list[Path]:
    """返回所有已登录账号的数据目录（按最近使用排序）"""
    candidates: list[Path] = []
    configured = os.environ.get("WECHAT_FILES_ROOT", "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    home = Path.home()
    candidates.extend(
        [
            home / "Documents" / "xwechat_files",
            home / "xwechat_files",
            home / "Documents" / "WeChat Files",
            home / "WeChat Files",
        ]
    )
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        drive = Path(f"{letter}:\\")
        if not drive.exists():
            continue
        candidates.extend(
            [
                drive / "xwechat_files",
                drive / "Documents" / "xwechat_files",
                drive / "WeChat Files",
                drive / "Documents" / "WeChat Files",
            ]
        )

    accs: list[Path] = []
    seen: set[str] = set()
    for base in candidates:
        try:
            if not base.exists():
                continue
            possible = [base] if (base / "db_storage").exists() else list(base.iterdir())
            for item in possible:
                if not item.is_dir() or not (item / "db_storage").exists():
                    continue
                key = str(item.resolve()).lower()
                if key not in seen:
                    seen.add(key)
                    accs.append(item)
        except Exception:
            continue
    try:
        accs.sort(key=lambda p: (p / "db_storage").stat().st_mtime, reverse=True)
    except Exception:
        pass
    return accs


def detect_wechat_version() -> str | None:
    """从安装目录的文件夹名读版本（微信把版本作为目录名）"""
    for root in (Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "Tencent" / "Weixin",
                 Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")) / "Tencent" / "WeChat"):
        try:
            if not root.exists():
                continue
            for d in root.iterdir():
                if d.is_dir() and re.fullmatch(r"\d+(\.\d+){2,3}", d.name):
                    return d.name
        except Exception:
            pass
    return None


def wechat_running() -> list[int]:
    pids = []
    for image_name in ("Weixin.exe", "WeChat.exe"):
        try:
            r = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for line in r.stdout.strip().split("\n"):
                parts = line.strip('"').split('","')
                if len(parts) >= 2 and parts[1].isdigit():
                    pids.append(int(parts[1]))
        except Exception:
            continue
    return sorted(set(pids))


def keytool_path() -> Path | None:
    """定位 wcdb-key-tool：优先脚本同目录，其次技能目录，再次数据目录"""
    here = Path(__file__).resolve().parent
    for p in (here / KEYTOOL_NAME,
              here.parent / KEYTOOL_NAME,
              DATA_DIR / KEYTOOL_NAME):
        if p.exists():
            return p
    return None


def ensure_keytool() -> Path | None:
    """若本地没有密钥工具，自动从 GitHub 下载"""
    p = keytool_path()
    if p:
        return p
    _print("  [*] 未找到密钥提取工具，尝试自动下载 ...")
    try:
        req = urllib.request.Request(KEYTOOL_URL_API, headers={"User-Agent": "capture.py"})
        with urllib.request.urlopen(req, timeout=40) as r:
            meta = json.load(r)
        import base64
        data = base64.b64decode(meta["content"])
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        p = DATA_DIR / KEYTOOL_NAME
        p.write_bytes(data)
        _print(f"  [+] 已下载到 {p}")
        return p
    except Exception as e:
        _print(f"  [!] 自动下载失败: {e}")
        return None


# ---------------------------------------------------------------- 数据访问

class Store:
    """封装解密后的数据库访问"""

    def __init__(self, account: Path, decrypted: Path):
        self.account = account
        self.d = decrypted
        self._contact = None

    @property
    def message_dbs(self) -> list[Path]:
        out = []
        for cand in ("message/message_0.db", "message/biz_message_0.db",
                     "message/message_1.db", "message/media_0.db"):
            p = self.d / cand
            if p.exists():
                out.append(p)
        if not out:
            out = sorted((self.d / "message").glob("message_*.db")) if (self.d / "message").exists() else []
        return out

    @property
    def self_username(self) -> str:
        """本人 wxid（账号目录名形如 wxid_xxx_05cf，去掉末尾 _随机后缀）"""
        name = self.account.name
        for cand in (name, name.rsplit("_", 1)[0] if "_" in name else name):
            p = self.d / "contact" / "contact.db"
            if p.exists():
                try:
                    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
                    hit = c.execute("select 1 from contact where username=?", (cand,)).fetchone()
                    c.close()
                except Exception:
                    hit = None
                if hit:
                    return cand
        return name

    def contacts(self) -> dict[str, str]:
        """username -> 显示名（备注优先，其次昵称）"""
        if self._contact is not None:
            return self._contact
        m: dict[str, str] = {}
        p = self.d / "contact" / "contact.db"
        if p.exists():
            try:
                c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
                for u, rk, nn in c.execute("select username, remark, nick_name from contact"):
                    if u:
                        m[u] = (rk or nn or u).strip()
                c.close()
            except Exception:
                pass
        self._contact = m
        return m

    def sessions(self, limit: int = 200) -> list[dict]:
        p = self.d / "session" / "session.db"
        if not p.exists():
            return []
        nick = self.contacts()
        c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        rows = c.execute(
            "select username, unread_count, last_timestamp, summary, last_sender_display_name "
            "from SessionTable order by sort_timestamp desc limit ?", (limit,)).fetchall()
        c.close()
        out = []
        for u, unread, ts, summ, snd in rows:
            out.append({
                "username": u,
                "name": nick.get(u, ""),
                "unread": unread or 0,
                "time": ts or 0,
                "summary": summ or "",
                "sender": snd or "",
            })
        return out

    def locate(self, keyword: str, limit: int = 15) -> list[dict]:
        """按关键词在会话与联系人里找匹配项"""
        kw = keyword.lower()
        hits, seen = [], set()

        for s in self.sessions(limit=2000):
            blob = f"{s['name']} {s['username']}".lower()
            if kw in blob:
                seen.add(s["username"])
                hits.append({**s, "source": "session"})

        nick = self.contacts()
        for u, n in nick.items():
            if u in seen:
                continue
            if kw in f"{n} {u}".lower():
                hits.append({"username": u, "name": n, "unread": 0, "time": 0,
                             "summary": "", "sender": "", "source": "contact"})
            if len(hits) >= limit:
                break
        return hits[:limit]

    # ---- 消息 ----

    def _table_for(self, username: str, db: Path) -> str | None:
        t = "Msg_" + hashlib.md5(username.encode()).hexdigest()
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        ok = c.execute("select 1 from sqlite_master where type='table' and name=?", (t,)).fetchone()
        c.close()
        return t if ok else None

    def messages(self, username: str, since: int, until: int | None = None,
                 limit: int = 500) -> list[dict]:
        """读取指定会话的消息；返回 [{'time','sender','type','text'}]"""
        out: list[dict] = []
        nick = self.contacts()
        zstd = _zstd_decompressor()

        for db in self.message_dbs:
            t = self._table_for(username, db)
            if not t:
                continue
            c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            sql = (f'select create_time, real_sender_id, local_type, message_content, '
                   f'WCDB_CT_message_content from "{t}" where create_time >= ? ')
            args: list = [since]
            if until:
                sql += "and create_time <= ? "
                args.append(until)
            sql += "order by create_time asc limit ?"
            args.append(limit)
            try:
                rows = c.execute(sql, args).fetchall()
            except Exception:
                c.close()
                continue
            c.close()

            idmap = self._sender_id_map(db)
            for ts, sid, ltype, content, ct in rows:
                raw = _decode_content(content, ct, zstd)
                text = clean_message(raw, ltype, nick, idmap.get(sid, ""))
                if text is None:
                    continue
                sender = idmap.get(sid, "")
                out.append({"time": ts, "sender": nick.get(sender, sender),
                            "is_self": bool(sender) and sender == self.self_username,
                            "type": MSG_TYPE.get(ltype, str(ltype)), "text": text})
            if out:
                break

        out.sort(key=lambda m: m["time"])
        return out[-limit:]

    def _sender_id_map(self, db: Path) -> dict[int, str]:
        """real_sender_id -> username（id 即 Name2Id 的 rowid）

        注意：必须显式取 rowid 并按 rowid 排序。Name2Id 以 user_name 为
        PRIMARY KEY，直接 `select user_name from Name2Id` 会走覆盖索引，
        返回的是 user_name 的字典序而非插入序，导致发送人张冠李戴。
        """
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = list(c.execute("select rowid, user_name from Name2Id order by rowid"))
        except Exception:
            rows = []
        c.close()
        return {int(rid): n for rid, n in rows if n}


_zstd_cache: dict = {}


def _zstd_decompressor():
    if "d" in _zstd_cache:
        return _zstd_cache["d"]
    try:
        import zstandard
        _zstd_cache["d"] = zstandard.ZstdDecompressor()
    except Exception:
        _zstd_cache["d"] = None
    return _zstd_cache["d"]


def _decode_content(content, ct, zstd) -> str:
    if content is None:
        return ""
    if isinstance(content, bytes):
        if ct == 4 or (len(content) >= 4 and content[:4] == b"\x28\xb5\x2f\xfd"):
            if zstd is None:
                return "[压缩消息：需 pip install zstandard 才能解压]"
            try:
                return zstd.decompress(content, max_output_size=8 * 1024 * 1024).decode("utf-8", "replace")
            except Exception:
                return "[压缩消息：解压失败]"
        try:
            return content.decode("utf-8", "replace")
        except Exception:
            return ""
    return str(content)


def clean_message(raw: str, ltype: int, nick: dict, sender: str) -> str | None:
    """清洗单条消息：去 XML、去系统噪音、媒体转占位符"""
    if not raw:
        return None
    # 群消息形如 "sender_xxx:\n内容"
    m = re.match(r"^([a-zA-Z0-9_\-@.]+):\n(.*)$", raw, re.S)
    body = m.group(2) if m else raw

    if ltype == 10000 or body.lstrip().startswith("<sysmsg"):
        if "撤回" in body or "加入" in body or "退出" in body or "拍了拍" in body:
            return None
        body = re.sub(r"<[^>]+>", "", body).strip()
        return body or None

    if ltype in (3, 34, 43, 47, 48, 50, 51):
        return f"[{MSG_TYPE.get(ltype, '媒体')}]"

    if ltype == 49 or "<msg>" in body or body.lstrip().startswith("<?xml"):
        title = re.search(r"<title>(.*?)</title>", body, re.S)
        des = re.search(r"<des>(.*?)</des>", body, re.S)
        appmsg = re.search(r'<appmsg[^>]*>.*?<type>(\d+)</type>', body, re.S)
        if title and title.group(1).strip():
            extra = des.group(1).strip() if des and des.group(1).strip() else ""
            return f"[分享] {title.group(1).strip()}" + (f" — {extra[:60]}" if extra else "")
        if appmsg:
            return "[分享/文件]"
        body = re.sub(r"<[^>]+>", " ", body)

    body = NOISE_RE.sub("", body)
    body = re.sub(r"\s+", " ", body).strip()
    if not body:
        return None
    return body[:2000]


# ---------------------------------------------------------------- 命令实现

def resolve_store(args) -> Store:
    accs = find_accounts()
    if not accs:
        _print("[ERROR] 未找到微信数据目录（Documents\\xwechat_files）")
        sys.exit(1)
    if getattr(args, "account", None):
        sel = None
        for a in accs:
            if args.account in a.name:
                sel = a
                break
        if sel is None:
            _print(f"[ERROR] 未找到账号 {args.account}，可用: {[a.name for a in accs]}")
            sys.exit(1)
    else:
        # 优先选已解密的账号，免去用户每次手动指定
        sel = next((a for a in accs if (DATA_DIR / "decrypted" / a.name).exists()), accs[0])
    dec = DATA_DIR / "decrypted" / sel.name
    if not dec.exists():
        _print(f"[ERROR] 尚未解密该账号的数据。请先运行: capture.py key && capture.py decrypt")
        _print(f"        期望目录: {dec}")
        sys.exit(1)
    return Store(sel, dec)


def cmd_doctor(_a):
    _print("=" * 60)
    _print("  微信信息抓取 · 环境自检 (Windows)")
    _print("=" * 60)

    _print("\n[1] 微信")
    ver = detect_wechat_version()
    _print(f"    版本: {ver or '未能识别'}")
    if ver:
        major = tuple(int(x) for x in ver.split(".")[:2])
        if major >= (4, 1):
            _print(f"    ✓ {VERSION_NOTE_OK}（运行时 Config.Cipher 扫描路径）")
        else:
            _print("    ✓ 4.0.x，走内存扫描路径")
    pids = wechat_running()
    _print(f"    {'✓ 运行中，PID: ' + str(pids[:5]) if pids else '✗ 未运行（提取密钥需要微信在线）'}")

    _print("\n[2] 数据目录")
    accs = find_accounts()
    if not accs:
        _print("    ✗ 未找到 wxid_* 数据目录")
    else:
        for a in accs:
            n = len(list((a / "db_storage").rglob("*.db")))
            _print(f"    ✓ {a.name}  ({n} 个数据库)")

    _print("\n[3] 密钥提取工具")
    kt = keytool_path()
    _print(f"    {'✓ ' + str(kt) if kt else '✗ 未安装（运行 capture.py key 会自动下载）'}")

    _print("\n[4] 密钥与解密库")
    if not accs:
        _print("    - 跳过")
    else:
        for a in accs:
            kf = DATA_DIR / f"keys_{a.name}.json"
            dd = DATA_DIR / "decrypted" / a.name
            k_ok = kf.exists()
            d_ok = dd.exists() and any(dd.rglob("*.db"))
            _print(f"    {a.name}: 密钥 {'✓' if k_ok else '✗'}  解密库 {'✓' if d_ok else '✗'}")

    _print("\n[5] 解压支持")
    if _zstd_decompressor():
        _print("    ✓ zstandard 可用，压缩消息可完整还原")
    else:
        _print("    ✗ 未安装 zstandard，约三成消息会显示为 [压缩消息]")
        _print("      修复: capture.py setup")

    _print("\n" + "=" * 60)
    ready = [a for a in accs
             if (DATA_DIR / f"keys_{a.name}.json").exists()
             and (DATA_DIR / "decrypted" / a.name).exists()]
    if ready:
        _print(f"  ✓ 已就绪（{len(ready)}/{len(accs)} 个账号已初始化）")
        for a in ready:
            _print(f"      · {a.name}")
        _print("  直接可用，试试: capture.py sessions")
        rest = [a for a in accs if a not in ready]
        if rest:
            _print(f"\n  另有 {len(rest)} 个账号未初始化，需要时执行:")
            _print(f"      capture.py key --account {rest[0].name}")
            _print(f"      capture.py decrypt --account {rest[0].name}")
    else:
        _print("  下一步: capture.py key  →  capture.py decrypt  →  capture.py sessions")
    _print("=" * 60)


def cmd_key(args):
    accs = find_accounts()
    if not accs:
        _print("[ERROR] 未找到微信数据目录")
        sys.exit(1)
    if not wechat_running():
        _print("[ERROR] 微信未运行。请登录微信后再试（密钥只在运行时驻留内存）")
        sys.exit(1)
    kt = ensure_keytool()
    if not kt:
        sys.exit(1)

    target = accs[0] if not args.account else next(
        (a for a in accs if args.account in a.name), None)
    if target is None:
        _print(f"[ERROR] 未找到账号 {args.account}")
        sys.exit(1)

    db_dir = target / "db_storage"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / f"keys_{target.name}.json"
    _print(f"[*] 账号: {target.name}")
    _print(f"[*] 库目录: {db_dir}")
    r = subprocess.run([sys.executable, str(kt), "extract", "--db-dir", str(db_dir),
                        "--output", str(out)])
    if r.returncode == 0 and out.exists():
        _print(f"\n[+] 密钥已保存: {out}")
        _print("[*] 下一步: capture.py decrypt")
    else:
        _print("\n[!] 提取失败。建议：在微信里退出登录再重新登录一次，然后立即重试")
        sys.exit(1)


def cmd_decrypt(args):
    accs = find_accounts()
    if not accs:
        _print("[ERROR] 未找到微信数据目录")
        sys.exit(1)
    kt = keytool_path() or ensure_keytool()
    if not kt:
        sys.exit(1)

    targets = [a for a in accs if (not args.account) or args.account in a.name]
    for t in targets:
        kf = DATA_DIR / f"keys_{t.name}.json"
        if not kf.exists():
            _print(f"[!] 跳过 {t.name}：无密钥文件，请先 capture.py key")
            continue
        out = DATA_DIR / "decrypted" / t.name
        _print(f"[*] 解密 {t.name} -> {out}")
        r = subprocess.run([sys.executable, str(kt), "decrypt",
                            "--keys", str(kf), "--output", str(out)])
        _print(f"    {'✓ 完成' if r.returncode == 0 else '✗ 失败'}")
    _print("\n[*] 下一步: capture.py sessions")


def _fmt_time(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")


def cmd_sessions(args):
    st = resolve_store(args)
    rows = st.sessions(limit=args.limit)
    _print(f"最近会话（{len(rows)} 个）\n" + "-" * 76)
    for s in rows:
        t = _fmt_time(s["time"]) if s["time"] else "  --  "
        tag = f"未读{s['unread']:<3}" if s["unread"] else "      "
        name = s["name"] or s["username"]
        _print(f"  {t}  {tag} {name[:26]:<28} {(s['summary'] or '')[:34]}")
    _print("-" * 76)
    _print("  用法: capture.py capture \"群名关键词\" --days 1")


def cmd_locate(args):
    st = resolve_store(args)
    hits = st.locate(args.keyword, limit=args.limit)
    if not hits:
        _print(f"未找到匹配「{args.keyword}」的会话或联系人")
        return
    _print(f"匹配「{args.keyword}」共 {len(hits)} 项:\n" + "-" * 76)
    for h in hits:
        src = "会话" if h.get("source") == "session" else "联系人"
        unread = f"未读{h['unread']}" if h.get("unread") else ""
        _print(f"  [{src}] {h['name'] or '(无备注)'}")
        _print(f"        username: {h['username']}  {unread}")
    _print("-" * 76)
    _print(f"  抓取: capture.py capture \"{hits[0]['name'] or hits[0]['username']}\" --days 1")


def cmd_capture(args):
    st = resolve_store(args)
    hits = st.locate(args.name, limit=10)
    if not hits:
        _print(f"未找到「{args.name}」")
        sys.exit(1)
    key = args.name.strip()
    exact = [h for h in hits if h["name"].strip() == key or h["username"] == key]
    sel = exact[0] if exact else hits[0]
    if not exact and len(hits) > 1:
        _print(f"[*] 匹配到多个，取第一个: {' | '.join(h['name'] or h['username'] for h in hits[:5])}")

    now = int(time.time())
    since = now - int(args.days * 86400) - int(args.hours * 3600)
    msgs = st.messages(sel["username"], since, limit=args.limit)

    title = sel["name"] or sel["username"]
    span = f"{_fmt_time(since)} ~ 现在"
    _print(f"=== {title} · {span} · {len(msgs)} 条 ===\n")
    if not msgs:
        _print("  （该时间范围内无消息）")
        return
    last_day = None
    for m in msgs:
        d = dt.datetime.fromtimestamp(m["time"]).strftime("%m-%d")
        if d != last_day:
            _print(f"--- {d} ---")
            last_day = d
        if m.get("is_self"):
            who = "我: "
        elif m["sender"] and m["sender"] != title:
            who = m["sender"] + ": "
        else:
            who = ""
        _print(f"  [{dt.datetime.fromtimestamp(m['time']).strftime('%H:%M')}] {who}{m['text']}")


def cmd_unread(args):
    st = resolve_store(args)
    rows = [s for s in st.sessions(limit=500) if s["unread"] > 0]
    if not rows:
        _print("没有未读消息")
        return
    rows.sort(key=lambda x: -x["unread"])
    total = sum(s["unread"] for s in rows)
    _print(f"未读汇总：{len(rows)} 个会话，共 {total} 条\n" + "-" * 76)
    for s in rows:
        _print(f"  {s['unread']:>4} 条   {s['name'] or s['username']}")
        if s["summary"]:
            _print(f"         最新: {s['summary'][:50]}")
    _print("-" * 76)


# ---------------------------------------------------------------- 安装

SKILL_MD = """---
name: 微信信息抓取
description: 读取本机 Windows 微信聊天记录并按主题汇总，支持定点关注某个群做定时监控。当用户要读微信聊天记录、监控某个群动态、汇总今日群聊、跟踪竞品群/客户群/行业群时调用此技能。仅适用于 Windows 平台，数据在本机处理。
slug: wechat-info-capture
---

# 微信信息抓取（Windows）

直接读取本机微信的本地数据库，输出干净文本供 AI 汇总。数据全程在本机，不上传。

## 何时使用

- 用户提到某个群/联系人的聊天内容，要求"读一下""总结""今天说了啥"
- 要求监控某个群（定时执行）
- 要求汇总未读消息

## 前置条件

1. Windows 10/11，微信 4.x 已登录并**保持运行**（密钥只在运行时驻留内存）
2. Python 3.9+（可选装 `pip install zstandard` 以还原压缩消息）
3. 首次使用需提取密钥并解密（见下）

## 运行环境要求（重要）

本技能读取的是**执行者本机**的微信数据，因此必须满足：

- 在装有微信的 **Windows 电脑**上运行
- 由**本机 WorkBuddy 客户端**执行

若技能被部署到云端/服务端执行，会找不到微信数据目录，只能返回空结果。

## 脚本位置

本技能的脚本是 `scripts/capture.py`。执行前先确定它的绝对路径：

- 用户级安装（最常见）：`%USERPROFILE%\\.workbuddy\\skills\\微信信息抓取\\scripts\\capture.py`
- 项目级安装：`{项目目录}\\.workbuddy\\skills\\微信信息抓取\\scripts\\capture.py`
- 若都不在，在 `.workbuddy\\skills` 下搜索 `capture.py`

下文命令中的 `capture.py` 均指该绝对路径。

## 首次配置（只需一次）

```
python scripts/capture.py setup      # 装可选依赖（还原压缩消息）
python scripts/capture.py key        # 从微信进程提取密钥（微信需运行中）
python scripts/capture.py decrypt    # 解密数据库到本地
python scripts/capture.py doctor     # 确认就绪
```

密钥提取失败时：在微信里**退出登录再重新登录**，然后立刻重试。
密钥只需取一次，之后长期有效（微信大版本更新后可能需重取）。

## 常用命令

```
python scripts/capture.py sessions              # 最近会话列表
python scripts/capture.py locate "客户"          # 定位群/联系人
python scripts/capture.py capture "客户群" --days 1   # 抓最近 1 天
python scripts/capture.py capture "客户群" --hours 6  # 抓最近 6 小时
python scripts/capture.py unread                # 未读汇总
python scripts/capture.py doctor                # 环境自检
```

所有路径可用 `--account wxid_xxx` 指定多账号中的某一个。

## 定点关注某个群（标准流程）

1. `locate "关键词"` → 拿到准确名称与 username
2. `capture "群名" --hours 1` → 验证能读到数据
3. 用自动化功能建立定时任务（如每小时一次），提示词写明群名与关注重点
4. **提醒用户：微信必须保持登录运行**，否则读不到新消息

## 输出处理

- 系统消息（入群/退群/撤回）已自动过滤
- 图片/语音/视频显示为 `[图片]` `[语音]` 等占位符
- 分享类消息提取标题
- 群消息格式为 `[时间] 发送者: 内容`

## 边界红线

- 仅处理用户**本人设备上的本人账号**数据
- 群聊内容涉及他人，汇总时避免输出个人手机号、身份证、住址等敏感信息
- 不得将聊天记录用于骚扰、人肉、未经授权的监控
- 数据不出本机，不得上传至任何外部服务
"""


def cmd_setup(_a):
    """补齐可选依赖：zstandard（用于还原约三成的压缩消息）"""
    if _zstd_decompressor():
        _print("✓ zstandard 已可用，无需安装")
        return
    _print("[*] 安装 zstandard 到当前 Python（--user，不污染系统目录）...")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--user", "zstandard"])
    if r.returncode == 0:
        _zstd_cache.pop("d", None)
        if _zstd_decompressor():
            _print("✓ 安装成功，压缩消息现在可完整还原")
        else:
            _print("! 安装完成但当前进程未能加载，请重新运行命令")
    else:
        _print("! 安装失败，可手动执行: pip install --user zstandard")


def cmd_install(_a):
    import shutil
    dest = Path.home() / ".workbuddy" / "skills" / "微信信息抓取"
    (dest / "scripts").mkdir(parents=True, exist_ok=True)
    (dest / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    shutil.copy2(Path(__file__).resolve(), dest / "scripts" / "capture.py")
    kt = keytool_path()
    if kt and kt.name != (dest / "scripts" / KEYTOOL_NAME).name:
        pass
    if kt:
        try:
            shutil.copy2(kt, dest / "scripts" / KEYTOOL_NAME)
        except Exception:
            pass
    _print(f"[+] 已安装到 {dest}")
    _print("    重启 WorkBuddy 后生效。")
    _print("\n首次使用请先执行:")
    _print("    python capture.py key  →  capture.py decrypt")


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="微信信息抓取 (Windows)")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("doctor", help="环境自检")
    p = sub.add_parser("key", help="提取数据库密钥")
    p.add_argument("--account", help="指定账号 wxid")
    p = sub.add_parser("decrypt", help="解密数据库")
    p.add_argument("--account", help="指定账号 wxid")

    for nm, h in (("sessions", "最近会话"), ("unread", "未读汇总")):
        q = sub.add_parser(nm, help=h)
        q.add_argument("--limit", type=int, default=200)
        q.add_argument("--account", help="指定账号 wxid")

    p = sub.add_parser("locate", help="定位群聊/联系人")
    p.add_argument("keyword")
    p.add_argument("--limit", type=int, default=15)
    p.add_argument("--account", help="指定账号 wxid")

    p = sub.add_parser("capture", help="抓取消息")
    p.add_argument("name")
    p.add_argument("--days", type=float, default=1)
    p.add_argument("--hours", type=float, default=0)
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--account", help="指定账号 wxid")

    sub.add_parser("setup", help="安装可选依赖 zstandard")
    sub.add_parser("install", help="安装为 WorkBuddy 技能")

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return
    {"doctor": cmd_doctor, "key": cmd_key, "decrypt": cmd_decrypt,
     "sessions": cmd_sessions, "locate": cmd_locate, "capture": cmd_capture,
     "unread": cmd_unread, "setup": cmd_setup, "install": cmd_install}[args.cmd](args)


if __name__ == "__main__":
    main()
