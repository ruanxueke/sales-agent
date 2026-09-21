"""通道管理：个人微信 / 公众号 统一状态入口"""
from __future__ import annotations
import logging
import socket
import time

import requests
from fastapi import APIRouter, Depends

from config.settings import settings
from core.security import require_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["channels"], dependencies=[Depends(require_api_key)])

_host_cache = {"host": "", "ts": 0.0}


def _candidate_hosts():
    env_host = getattr(settings, "BOT_HOST", "").strip()
    if env_host:
        yield env_host
    yield "host.docker.internal"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("223.5.5.5", 80))
        ip = s.getsockname()[0]
        s.close()
        yield ip
    except Exception as e:
        logger.debug("_candidate_hosts 异常已忽略: %s", e)
    yield "127.0.0.1"


def _pick_bot_host():
    cached = _host_cache["host"]
    if cached and time.time() - _host_cache["ts"] < 60:
        return cached
    port = getattr(settings, "BOT_NOTIFY_PORT", 3900)
    for host in _candidate_hosts():
        try:
            r = requests.get(f"http://{host}:{port}/status", timeout=1.5)
            if r.ok:
                _host_cache["host"] = host
                _host_cache["ts"] = time.time()
                return host
        except Exception:
            continue
    return _host_cache["host"] or "host.docker.internal"


def _bot_get(path: str, timeout: float = 3.0):
    host = _pick_bot_host()
    port = getattr(settings, "BOT_NOTIFY_PORT", 3900)
    # 连接和读取分开限时，机器人端口不可达时快速失败，不拖住中台
    return requests.get(f"http://{host}:{port}{path}", timeout=(1.5, timeout))


def _bot_post(path: str, payload: dict, timeout: float = 3.0):
    host = _pick_bot_host()
    port = getattr(settings, "BOT_NOTIFY_PORT", 3900)
    return requests.post(f"http://{host}:{port}{path}", json=payload, timeout=(1.5, timeout))

@router.get("/channels/wechat/status")
async def wechat_status():
    try:
        r = _bot_get("/status")
        status = r.json() if r.ok else {}
        return {
            "configured": True,
            "online": bool(status.get("online")),
            "bot_name": status.get("bot_name") or "",
            "target_room": status.get("target_room") or "",
            "require_mention": bool(status.get("require_mention")),
            "personal_auto_reply": bool(status.get("personal_auto_reply")),
            "pid": status.get("pid"),
            "uptime_sec": status.get("uptime_sec", 0),
            "last_log": status.get("last_log") or "",
            "error": "" if r.ok else f"HTTP {r.status_code}",
        }
    except Exception as e:
        logger.warning("个人微信状态获取失败: %s", e)
        return {
            "configured": True,
            "online": False,
            "bot_name": "",
            "target_room": "",
            "require_mention": False,
            "personal_auto_reply": False,
            "pid": None,
            "uptime_sec": 0,
            "last_log": "",
            "error": "机器人控制服务未响应",
        }


@router.get("/channels/wechat/qrcode")
async def wechat_qrcode():
    try:
        r = _bot_get("/qrcode")
        data = r.json() if r.ok else {}
        return {"qr_url": data.get("qr_url") or "", "qr_path": data.get("qr_path") or "", "error": "" if r.ok else f"HTTP {r.status_code}"}
    except Exception as e:
        logger.warning("个人微信二维码获取失败: %s", e)
        return {"qr_url": "", "qr_path": "", "error": "机器人控制服务未响应"}


@router.get("/channels/wechat/logs")
async def wechat_logs(limit: int = 50):
    try:
        r = _bot_get("/logs")
        data = r.json() if r.ok else {}
        lines = (data.get("lines") or [])[-limit:]
        return {"lines": lines, "error": "" if r.ok else f"HTTP {r.status_code}"}
    except Exception as e:
        logger.warning("个人微信日志获取失败: %s", e)
        return {"lines": [], "error": "机器人控制服务未响应"}

@router.get("/channels/wechat/config")
async def wechat_get_config():
    try:
        r = _bot_get("/config")
        data = r.json() if r.ok else {}
        return {**data, "error": "" if r.ok else f"HTTP {r.status_code}"}
    except Exception as e:
        logger.warning("个人微信配置获取失败: %s", e)
        return {"ok": False, "error": "机器人控制服务未响应"}

@router.post("/channels/wechat/config")
async def wechat_set_config(req: dict):
    try:
        r = _bot_post("/config", req)
        data = r.json() if r.ok else {}
        return {**data, "error": "" if r.ok else f"HTTP {r.status_code}"}
    except Exception as e:
        logger.warning("个人微信配置保存失败: %s", e)
        return {"ok": False, "error": "机器人控制服务未响应"}


@router.get("/channels/overview")
async def channels_overview():
    from core.monitor import monitor
    summary = monitor.summary(300)
    heartbeats = {}
    for src, seen in summary.get("bots", {}).items():
        heartbeats[src] = {"online": seen, "last_seen": seen}
    heartbeats = {}
    try:
        from core import sql_compat as sqlite3  # SQL 统一指向 DATABASE_URL，避免与 ORM 分叉
        from pathlib import Path
        from datetime import datetime
        db = Path(settings.DATA_DIR) / "metrics.db"
        if db.exists():
            conn = sqlite3.connect(str(db))
            for row in conn.execute("SELECT source, last_seen FROM heartbeats").fetchall():
                online = False
                try:
                    dt = datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S")
                    online = (datetime.now() - dt).total_seconds() < 90
                except Exception as e:
                    logger.debug("channels_overview 异常已忽略: %s", e)
                heartbeats[row[0]] = {"online": online, "last_seen": row[1]}
            conn.close()
    except Exception as e:
        logger.warning("心跳记录读取失败: %s", e)

    official = {
        "app_id": getattr(settings, "WECHAT_OFFICIAL_APP_ID", "") or "",
        "configured": bool(getattr(settings, "WECHAT_OFFICIAL_APP_ID", "") and getattr(settings, "WECHAT_OFFICIAL_APP_SECRET", "")),
        "callback_url": "/wechat",
    }
    wecom = {
        "configured": bool(getattr(settings, "WECOM_CORP_ID", "") and getattr(settings, "WECOM_CONTACT_SECRET", "") and getattr(settings, "WECOM_AGENT_ID", "")),
        "corp_id": getattr(settings, "WECOM_CORP_ID", "") or "",
        "callback_url": f"{getattr(settings, 'PUBLIC_BASE_URL', 'http://127.0.0.1:5000').rstrip('/')}/wecom",
    }
    return {"official": official, "wechat": {"heartbeat": heartbeats.get("wechat", {})}, "wecom": wecom}
