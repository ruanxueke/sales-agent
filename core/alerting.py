"""企业级监控告警：机器人掉线 / 接口错误率 / 回复超时，多通道通知 + 规则管理 + 防重复"""
from __future__ import annotations
import logging
from core import sql_compat as sqlite3  # SQL 统一指向 DATABASE_URL，避免与 ORM 分叉
import threading
from datetime import datetime, timedelta
from pathlib import Path

import requests

from config.settings import settings

logger = logging.getLogger(__name__)

DB_PATH = Path(settings.DATA_DIR) / "customers.db"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class AlertManager:
    def __init__(self):
        self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._init()

    def _init(self):
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS alert_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rule_type TEXT,
                    name TEXT,
                    enabled INTEGER DEFAULT 1,
                    threshold REAL DEFAULT 0,
                    window_seconds INTEGER DEFAULT 300,
                    channels TEXT DEFAULT 'webhook',
                    receivers TEXT DEFAULT '',
                    cooldown_seconds INTEGER DEFAULT 600,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS alert_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rule_id INTEGER,
                    rule_type TEXT,
                    title TEXT,
                    content TEXT,
                    level TEXT DEFAULT 'warning',
                    status TEXT DEFAULT 'sent',
                    sent_at TEXT
                );
                """
            )
            # 默认规则
            defaults = [
                ("bot_offline", "机器人掉线", 90, 300, "webhook", "叙白", 600),
                ("api_error_rate", "接口错误率过高", 5.0, 300, "webhook", "叙白", 600),
                ("slow_reply", "回复超时", 30000, 300, "webhook", "叙白", 600),
            ]
            for row in defaults:
                n = self._conn.execute(
                    "SELECT COUNT(*) FROM alert_rules WHERE rule_type=?", (row[0],)
                ).fetchone()[0]
                if n == 0:
                    self._conn.execute(
                        "INSERT INTO alert_rules (rule_type,name,enabled,threshold,window_seconds,channels,receivers,cooldown_seconds,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (row[0], row[1], 1, row[2], row[3], row[4], row[5], row[6], _now()),
                    )
            self._conn.commit()

    def list_rules(self) -> list[dict]:
        return [dict(r) for r in self._conn.execute("SELECT * FROM alert_rules ORDER BY id").fetchall()]

    def list_events(self, limit: int = 100) -> list[dict]:
        return [dict(r) for r in self._conn.execute("SELECT * FROM alert_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

    def upsert_rule(self, rule_id: int | None, **fields) -> dict:
        allowed = {"rule_type", "name", "enabled", "threshold", "window_seconds", "channels", "receivers", "cooldown_seconds"}
        data = {k: v for k, v in fields.items() if k in allowed}
        with self._lock:
            if rule_id:
                sets = ",".join(f"{k}=?" for k in data)
                self._conn.execute(f"UPDATE alert_rules SET {sets} WHERE id=?", list(data.values()) + [rule_id])
            else:
                cur = self._conn.execute(
                    "INSERT INTO alert_rules (rule_type,name,enabled,threshold,window_seconds,channels,receivers,cooldown_seconds,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (data.get("rule_type", ""), data.get("name", ""), data.get("enabled", 1), data.get("threshold", 0),
                     data.get("window_seconds", 300), data.get("channels", "webhook"), data.get("receivers", ""), data.get("cooldown_seconds", 600), _now()),
                )
                rule_id = cur.lastrowid
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM alert_rules WHERE id=?", (rule_id,)).fetchone()
            return dict(row)

    def delete_rule(self, rule_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM alert_rules WHERE id=?", (rule_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def _in_cooldown(self, rule_id: int, cooldown: int) -> bool:
        row = self._conn.execute(
            "SELECT sent_at FROM alert_events WHERE rule_id=? ORDER BY id DESC LIMIT 1", (rule_id,)
        ).fetchone()
        if not row:
            return False
        try:
            last = datetime.strptime(row["sent_at"], "%Y-%m-%d %H:%M:%S")
            return (datetime.now() - last).total_seconds() < cooldown
        except Exception:
            return False

    def _send_channels(self, title: str, content: str, channels: str, receivers: str) -> str:
        """按通道发送；未配置外部通道时写入中台通知（webhook/飞书/钉钉/企微占位）"""
        sent = []
        channels_list = [c.strip() for c in (channels or "webhook").split(",") if c.strip()]
        text = f"[销售智能体告警] {title}\n{content}"
        if settings.ALERT_WEBHOOK_URL and "webhook" in channels_list:
            try:
                requests.post(settings.ALERT_WEBHOOK_URL, json={"msgtype": "text", "text": {"content": text}}, timeout=5)
                sent.append("webhook")
            except Exception as e:
                logger.warning("Webhook 告警发送失败: %s", e)
        if "notify" in channels_list or not sent:
            try:
                # 机器人运行在宿主机，容器内需通过 host.docker.internal 访问
                hosts = [getattr(settings, "BOT_HOST", "") or "host.docker.internal", "127.0.0.1"]
                resp = None
                for h in hosts:
                    try:
                        resp = requests.post(
                            f"http://{h}:{settings.BOT_NOTIFY_PORT}/notify",
                            json={"target_name": receivers or "叙白", "content": text},
                            timeout=5,
                        )
                        if resp.ok:
                            break
                    except Exception:
                        resp = None
                        continue
                if resp.ok:
                    sent.append("notify")
                else:
                    logger.warning("通知服务返回: %s", resp.status_code)
            except Exception as e:
                logger.warning("中台通知失败: %s", e)
        return ",".join(sent)

    def fire(self, rule_type: str, title: str, content: str, level: str = "warning"):
        rule = None
        for r in self.list_rules():
            if r["rule_type"] == rule_type:
                rule = r
                break
        if not rule or not rule.get("enabled"):
            return
        if self._in_cooldown(rule["id"], rule.get("cooldown_seconds") or 600):
            return
        with self._lock:
            channels = self._send_channels(title, content, rule.get("channels") or "webhook", rule.get("receivers") or "")
            self._conn.execute(
                "INSERT INTO alert_events (rule_id,rule_type,title,content,level,status,sent_at) VALUES (?,?,?,?,?,?,?)",
                (rule["id"], rule_type, title, content, level, "sent" if channels else "failed", _now()),
            )
            self._conn.commit()
            logger.warning("告警触发: %s | %s | 通道=%s", rule_type, title, channels or "无")

    def check_bot(self):
        """机器人掉线：heartbeats 中 wechat 超过阈值未上报"""
        try:
            from core.monitor import monitor
            s = monitor.summary(9999)
            if not s.get("bots", {}).get("wechat"):
                self.fire("bot_offline", "个人微信机器人掉线", "心跳超过 90 秒未上报，请检查 pm2 进程", "critical")
        except Exception as e:
            logger.warning("机器人掉线检查失败: %s", e)

    def check_api_error(self):
        """接口错误率：最近窗口内错误率超过阈值"""
        try:
            from core.monitor import monitor
            rule = next((r for r in self.list_rules() if r["rule_type"] == "api_error_rate"), None)
            window = int(rule.get("window_seconds") or 300) if rule else 300
            s = monitor.summary(window)
            rate = s.get("error_rate") or 0
            threshold = float(rule.get("threshold") or 5.0) if rule else 5.0
            if s.get("total_requests", 0) >= 10 and rate >= threshold:
                self.fire("api_error_rate", f"接口错误率过高 {rate}%", f"最近 {window}s 共 {s.get('total_requests')} 请求，错误 {s.get('error_count')} 次")
        except Exception as e:
            logger.warning("错误率检查失败: %s", e)

    def check_slow_reply(self):
        """回复超时：最近窗口内 LLM 调用 P95 超过阈值"""
        try:
            from core.llm_trace import llm_trace_manager
            rule = next((r for r in self.list_rules() if r["rule_type"] == "slow_reply"), None)
            threshold = float(rule.get("threshold") or 30000) if rule else 30000
            traces = llm_trace_manager.list(limit=200)
            if not traces:
                return
            latencies = [t.get("latency_ms") or 0 for t in traces if isinstance(t, dict)]
            if not latencies:
                return
            latencies.sort()
            p95 = latencies[min(int(len(latencies) * 0.95), len(latencies) - 1)]
            if p95 >= threshold:
                self.fire("slow_reply", f"AI 回复超时 P95={p95}ms", f"最近 {len(latencies)} 次调用，超阈值 {threshold}ms")
        except Exception as e:
            logger.warning("慢响应检查失败: %s", e)

    def run_checks(self):
        self.check_bot()
        self.check_api_error()
        self.check_slow_reply()

    def test_send(self, title: str = "测试告警", content: str = "这是一条测试告警，确认通知通道正常。") -> dict:
        rule = self.list_rules()[0] if self.list_rules() else None
        channels = rule.get("channels") if rule else "webhook"
        receivers = rule.get("receivers") if rule else ""
        sent = self._send_channels(title, content, channels, receivers)
        return {"ok": bool(sent), "channels": sent or "无可用通道"}


alert_manager = AlertManager()
