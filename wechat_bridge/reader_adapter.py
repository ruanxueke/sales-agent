"""封装微信信息抓取 Skill，只读取配置白名单会话。"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

from wechat_bridge.config import BridgeConfig, TargetConfig

logger = logging.getLogger("wechat_bridge")


class CaptureUnavailable(RuntimeError):
    pass


def bundled_capture_dir() -> Path:
    """随桥接一起分发的内置读取器目录（wechat_bridge/vendor）。"""
    return Path(__file__).resolve().parent / "vendor"


def find_capture_script(configured: str = "") -> Path:
    """定位读取器 capture.py。

    顺序：显式配置 → 环境变量 → **内置 vendor（商用分发主路径）** → 本机 WorkBuddy 技能目录。
    内置优先，装到客户机上就不再依赖 ~/.workbuddy/skills 是否存在。
    """
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    env_path = os.getenv("WECHAT_CAPTURE_SCRIPT")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(bundled_capture_dir() / "capture.py")
    candidates.extend(
        [
            Path.home() / ".workbuddy" / "skills" / "微信信息抓取" / "scripts" / "capture.py",
            Path.home() / ".workbuddy" / "skills" / "微信读取助手" / "scripts" / "capture.py",
        ]
    )
    skills_dir = Path.home() / ".workbuddy" / "skills"
    if skills_dir.exists():
        candidates.extend(skills_dir.glob("*/scripts/capture.py"))
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise CaptureUnavailable(
        "未找到微信读取器 capture.py（内置目录 %s 也没有）" % bundled_capture_dir()
    )


class CaptureReader:
    def __init__(self, config: BridgeConfig):
        self.config = config
        self.capture_path = find_capture_script(config.capture_script)
        self.module = self._load_module(self.capture_path)
        if config.wechat_files_root:
            os.environ["WECHAT_FILES_ROOT"] = config.wechat_files_root
        self.account_source = ""
        self.account_candidates: list[str] = []
        self.account = self._select_account(config.account_id)
        decrypted = self.module.DATA_DIR / "decrypted" / self.account.name
        if not (decrypted.exists() and any(decrypted.rglob("*.db"))):
            raise CaptureUnavailable(
                f"微信账号尚未解密: {self.account.name}。请先执行 capture.py key 和 decrypt"
            )
        self.store = self.module.Store(self.account, decrypted)
        self.self_usernames = set(config.self_usernames)
        # 当前账号自己的 wxid 一定算「自己」，否则会把自动回复当成客户消息回读，
        # 造成自问自答。配置里可能残留别的机器上的 wxid，这里始终补上本机账号。
        if self.account.name.startswith("wxid_"):
            self.self_usernames.add(self.account.name.rsplit("_", 1)[0])
        self._last_refresh = 0.0

    @staticmethod
    def _load_module(path: Path):
        spec = importlib.util.spec_from_file_location("wechat_capture_skill", path)
        if spec is None or spec.loader is None:
            raise CaptureUnavailable(f"无法加载微信读取工具: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _decrypted_dir(self, account) -> Path:
        return self.module.DATA_DIR / "decrypted" / account.name

    def _is_decrypted(self, account) -> bool:
        decrypted = self._decrypted_dir(account)
        return decrypted.exists() and any(decrypted.rglob("*.db"))

    def _select_account(self, requested: str):
        accounts = self._find_accounts()
        if not accounts:
            raise CaptureUnavailable(
                "未找到本机微信数据目录。已检查默认目录、其他磁盘常见目录和配置路径；"
                "请在微信“设置 -> 文件管理”中确认数据目录，并在修复脚本中填写该路径。"
                "请确认微信已登录并生成过聊天数据"
            )
        names = [account.name for account in accounts]
        self.account_candidates = names
        if requested:
            for account in accounts:
                if requested == account.name or requested in account.name:
                    if not self._is_decrypted(account):
                        raise CaptureUnavailable(
                            f"微信账号 {account.name} 尚未解密，"
                            f"请先执行 capture.py key 和 decrypt（数据目录 "
                            f"{self._decrypted_dir(account)}）"
                        )
                    self.account_source = "config"
                    return account
            raise CaptureUnavailable(
                f"未找到微信账号 {requested}；本机可用账号：{', '.join(names)}"
            )

        # 只能在「已解密」的账号里挑。机器上常有多个微信账号，
        # 但只有被解密过的才读得到数据，挑到没解密的账号会整条链路起不来。
        usable = [account for account in accounts if self._is_decrypted(account)]
        if not usable:
            raise CaptureUnavailable(
                "本机没有可用于读取的微信账号（以下账号都尚未解密）："
                + ", ".join(names)
                + f"。请先执行 capture.py key 和 decrypt，解密目录：{self.module.DATA_DIR / 'decrypted'}"
            )
        if len(usable) > 1:
            logger.warning(
                "本机检测到 %d 个已解密微信账号（%s），默认选用最近使用的 %s；"
                "如需固定，请在配置里显式填写 account_id",
                len(usable),
                ", ".join(account.name for account in usable),
                usable[0].name,
            )

        # 优先复用上一次已解析的账号，避免按 mtime 排序结果漂移导致读错账号、回复错人。
        remembered = self._read_remembered_account()
        if remembered:
            for account in usable:
                if account.name == remembered:
                    self.account_source = "remembered"
                    return account
        self.account_source = "recent"
        self._remember_account(usable[0].name)
        return usable[0]

    def _find_accounts(self) -> list[Path]:
        accounts = list(self.module.find_accounts())
        seen = {str(path.resolve()).lower() for path in accounts}
        for path in self._scan_wechat_accounts():
            key = str(path.resolve()).lower()
            if key not in seen:
                seen.add(key)
                accounts.append(path)
        try:
            accounts.sort(
                key=lambda path: (path / "db_storage").stat().st_mtime,
                reverse=True,
            )
        except Exception:
            pass
        return accounts

    @staticmethod
    def _scan_wechat_accounts(max_depth: int = 4, max_dirs: int = 30000) -> list[Path]:
        roots = [Path.home()]
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            drive = Path(f"{letter}:\\")
            if drive.exists():
                roots.append(drive)
        skip_names = {
            "$recycle.bin",
            "windows",
            "program files",
            "program files (x86)",
            "programdata",
            "system volume information",
            "node_modules",
            "__pycache__",
        }
        found: list[Path] = []
        seen: set[str] = set()
        queue = deque((root, 0) for root in roots)
        visited = 0
        while queue and visited < max_dirs:
            current, depth = queue.popleft()
            visited += 1
            try:
                normalized_name = (
                    current.name.lower()
                    .replace(" ", "")
                    .replace("_", "")
                    .replace("-", "")
                )
                if "wechat" in normalized_name or "wechatfiles" in normalized_name:
                    if (current / "db_storage").exists():
                        key = str(current.resolve()).lower()
                        if key not in seen:
                            seen.add(key)
                            found.append(current)
                    elif depth < max_depth:
                        for entry in os.scandir(current):
                            try:
                                if entry.is_dir(follow_symlinks=False) and (Path(entry.path) / "db_storage").exists():
                                    key = str(Path(entry.path).resolve()).lower()
                                    if key not in seen:
                                        seen.add(key)
                                        found.append(Path(entry.path))
                            except OSError:
                                continue
                    continue
                if depth >= max_depth:
                    continue
                for entry in os.scandir(current):
                    try:
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                        if entry.name.lower() in skip_names:
                            continue
                        queue.append((Path(entry.path), depth + 1))
                    except OSError:
                        continue
            except OSError:
                continue
        return found

    def _account_memory_path(self) -> Path:
        state_path = self.config.state_path or ""
        base = Path(state_path).expanduser().parent if state_path else Path.cwd()
        return base / "resolved_account.json"

    def _read_remembered_account(self) -> str:
        try:
            data = json.loads(self._account_memory_path().read_text(encoding="utf-8"))
            return str(data.get("account_id") or "")
        except (OSError, ValueError):
            return ""

    def _remember_account(self, account_id: str) -> None:
        try:
            path = self._account_memory_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"account_id": account_id}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("记住当前账号失败，多账号场景下可能识别到其它账号: %s", e)

    def resolve_target(self, target: TargetConfig) -> dict:
        if target.target_username:
            nicknames = self._nicknames()
            return {
                "username": target.target_username,
                "name": nicknames.get(target.target_username, "")
                or target.target_name
                or target.target_username,
            }
        hits = self.store.locate(target.target_name, limit=10)
        exact = [
            hit
            for hit in hits
            if (hit.get("name") or "").strip() == target.target_name.strip()
            or hit.get("username") == target.target_name.strip()
        ]
        if len(exact) == 1:
            return exact[0]
        if not exact:
            raise CaptureUnavailable(f"未找到目标会话: {target.target_name}")
        raise CaptureUnavailable(f"目标会话存在多个精确匹配: {target.target_name}")

    def read_messages(
        self,
        target: TargetConfig,
        lookback_seconds: int | None = None,
        limit: int = 100,
    ) -> list[dict]:
        self.refresh()
        resolved = self.resolve_target(target)
        now = int(time.time())
        since = now - int(lookback_seconds or self.config.message_lookback_seconds)
        rows = self._read_messages_with_direction(
            resolved["username"],
            since,
            until=now,
            limit=limit,
        )
        output = []
        for row in rows:
            output.append(
                {
                    **row,
                    "target_name": resolved.get("name") or target.target_name,
                    "target_username": resolved["username"],
                }
            )
        return output

    def refresh(self, force: bool = False) -> dict:
        if not self.config.decrypt_before_read:
            return {"ok": True, "skipped": True}
        now = time.time()
        if not force and now - self._last_refresh < self.config.decrypt_interval_seconds:
            return {"ok": True, "cached": True}
        command = [
            sys.executable,
            str(self.capture_path),
            "decrypt",
            "--account",
            self.account.name,
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=120,
        )
        if result.returncode != 0:
            raise CaptureUnavailable(
                f"微信数据刷新失败: {(result.stderr or result.stdout or '').strip()[:300]}"
            )
        decrypted = self.module.DATA_DIR / "decrypted" / self.account.name
        self.store = self.module.Store(self.account, decrypted)
        self._last_refresh = now
        return {"ok": True, "account_id": self.account.name}

    def find_outgoing(
        self,
        target: TargetConfig,
        content: str,
        since: int,
        limit: int = 100,
    ) -> bool:
        expected = (content or "").strip()
        if not expected:
            return False
        self.refresh(force=True)
        resolved = self.resolve_target(target)
        rows = self._read_messages_with_direction(
            resolved["username"],
            since,
            limit=limit,
        )
        for row in rows:
            if row.get("is_self") and str(row.get("text") or "").strip() == expected:
                return True
        return False

    def list_customer_sessions(
        self,
        since: int | None,
        limit: int = 500,
    ) -> list[dict]:
        """返回可能为客户私聊的会话；群聊、公众号和系统号会被跳过。"""
        self.refresh()
        excluded = {
            "filehelper",
            "fmessage",
            "floatbottle",
            "notifymessage",
            "brandsessionholder",
            "brandservicesessionholder",
        }
        excluded.update(self.config.excluded_usernames)
        nicknames = self._nicknames()
        output = []
        for session in self.store.sessions(limit=2000):
            username = str(session.get("username") or "").strip()
            name = str(nicknames.get(username) or session.get("name") or "").strip()
            timestamp = int(session.get("time") or 0)
            if not username or not name or (since is not None and timestamp < since):
                continue
            if username.endswith("@chatroom"):
                continue
            if username.startswith("gh_") or username in excluded:
                continue
            output.append(
                {
                    "username": username,
                    "name": name,
                    "unread": int(session.get("unread") or 0),
                    "time": timestamp,
                    "summary": str(session.get("summary") or ""),
                }
            )
            if len(output) >= limit:
                break
        return output

    def _read_messages_with_direction(
        self,
        username: str,
        since: int,
        until: int | None = None,
        limit: int = 500,
    ) -> list[dict]:
        """读取消息，并按正确的 Name2Id rowid 识别是否为自己发送。"""
        output: list[dict] = []
        contacts = self.store.contacts()
        nicknames = self._nicknames()
        zstd = self.module._zstd_decompressor()
        for db in self.store.message_dbs:
            table = self.store._table_for(username, db)
            if not table:
                continue
            sql = (
                f'select create_time, real_sender_id, local_type, message_content, '
                f'WCDB_CT_message_content from "{table}" where create_time >= ? '
            )
            args: list = [since]
            if until:
                sql += "and create_time <= ? "
                args.append(until)
            sql += "order by create_time asc limit ?"
            args.append(limit)
            try:
                connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
                rows = connection.execute(sql, args).fetchall()
            except Exception:
                continue
            finally:
                try:
                    connection.close()
                except Exception as e:
                    logger.debug("CaptureReader._read_messages_with_direction 异常已忽略: %s", e)

            sender_map = self._sender_map_by_rowid(db)
            for timestamp, sender_id, local_type, content, content_type in rows:
                raw = self.module._decode_content(content, content_type, zstd)
                sender_username = sender_map.get(int(sender_id or 0), "")
                text = self.module.clean_message(
                    raw,
                    int(local_type or 0),
                    contacts,
                    sender_username,
                )
                if text is None:
                    continue
                output.append(
                    {
                        "time": timestamp,
                        "sender": nicknames.get(
                            sender_username,
                            contacts.get(sender_username, sender_username),
                        ),
                        "sender_username": sender_username,
                        "is_self": sender_username in self.self_usernames,
                        "type": self.module.MSG_TYPE.get(
                            int(local_type or 0),
                            str(local_type),
                        ),
                        "text": text,
                    }
                )
        deduped = {}
        for item in output:
            key = (
                item["time"],
                item.get("sender_username") or "",
                item.get("text") or "",
            )
            deduped[key] = item
        merged = list(deduped.values())
        merged.sort(key=lambda item: item["time"])
        return merged[-limit:]

    @staticmethod
    def _sender_map_by_rowid(db: Path) -> dict[int, str]:
        connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return {
                int(row_id): username
                for row_id, username in connection.execute(
                    "select rowid, user_name from Name2Id"
                )
            }
        finally:
            connection.close()

    def _nicknames(self) -> dict[str, str]:
        """客户显示名统一优先使用微信备注名，无备注时回退原始昵称。"""
        db = self.store.d / "contact" / "contact.db"
        if not db.exists():
            return {}
        connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            output = {}
            for username, nickname, remark in connection.execute(
                "select username, nick_name, remark from contact"
            ):
                if username:
                    output[str(username)] = str(
                        remark or nickname or username
                    ).strip()
            return output
        finally:
            connection.close()

    def health(self) -> dict:
        contacts = self.store.contacts()
        nicknames = self._nicknames()
        targets = []
        for target in self.config.targets:
            try:
                resolved = self.resolve_target(target)
                targets.append(
                    {
                        "target": resolved.get("name") or target.target_name,
                        "ok": True,
                        **resolved,
                    }
                )
            except Exception as exc:
                targets.append(
                    {
                        "target": target.target_name,
                        "ok": False,
                        "error": str(exc),
                    }
                )
        return {
            "ok": all(item["ok"] for item in targets) if targets else bool(self.account),
            "capture_script": str(self.capture_path),
            "bundled": str(self.capture_path).startswith(str(bundled_capture_dir())),
            "account_id": self.account.name,
            "account_source": self.account_source,
            "account_candidates": self.account_candidates,
            "self_usernames": sorted(self.self_usernames),
            "self_name": contacts.get(self.account.name, ""),
            "targets": targets,
        }

    def detect_wechat_login(self) -> dict:
        """检测微信进程、登录窗口和当前账号数据是否可用。"""
        process_ids = []
        try:
            process_ids = list(self.module.wechat_running())
        except Exception:
            process_ids = []
        window_found = False
        try:
            import pygetwindow

            titles = [
                str(getattr(window, "title", "") or "").strip()
                for window in pygetwindow.getAllWindows()
            ]
            expected = str(self.config.window_title or "").strip()
            window_found = any(
                title == expected
                or "微信" in title
                or title.lower() in {"wechat", "weixin"}
                for title in titles
                if title
            )
        except Exception:
            window_found = False
        account_data = (
            self.store.d.exists()
            and any(self.store.d.rglob("*.db"))
        )
        account_name = ""
        try:
            contacts = self.store.contacts()
            self_username = self.store.self_username
            account_name = (
                contacts.get(self_username)
                or contacts.get(self.account.name)
                or ""
            )
        except Exception:
            account_name = ""
        return {
            "logged_in": bool(process_ids and account_data),
            "process_running": bool(process_ids),
            "window_found": window_found,
            "account_data": account_data,
            "account_id": self.account.name,
            "account_name": account_name,
        }
