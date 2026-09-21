"""企业级系统自检：数据库、向量库、模型、通道、监控、备份"""
from __future__ import annotations
import logging
import time
from pathlib import Path

import json

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from config.settings import settings
from core.security import current_tenant, require_admin, require_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["system"], dependencies=[Depends(require_api_key)])


class RouterSwitch(BaseModel):
    model: str = "auto"


@router.get("/system/self-check", dependencies=[Depends(require_admin)])
async def self_check(request: Request):
    checks = []

    def add(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)})

    try:
        from sqlalchemy import text
        from core.db import init_db, SessionLocal
        init_db()
        with SessionLocal() as s:
            s.execute(text("SELECT 1"))
        add("数据库", True, "SQLite 连接正常")
    except Exception as e:
        add("数据库", False, str(e)[:120])

    try:
        from core.vector_store import KnowledgeStore
        store = KnowledgeStore(tenant_id=current_tenant(request))
        add(
            "向量库",
            True,
            f"{store.backend_name} / {store.count()} 条向量",
        )
    except Exception as e:
        add("向量库", False, str(e)[:120])

    add("DeepSeek 模型", bool(settings.DEEPSEEK_API_KEY),
        "已配置" if settings.DEEPSEEK_API_KEY else "未配置")
    try:
        from core.llm_router import llm_router
        info = llm_router.status()
        if info["backup_configured"]:
            add("备用模型", True, f"{info['backup_provider']} / {info['backup_model']}")
        else:
            add("备用模型", True, "框架已就绪，未配置备用模型（位置预留）")
    except Exception as e:
        add("备用模型", False, str(e)[:120])
    add("公众号通道", bool(settings.WECHAT_OFFICIAL_APP_ID and settings.WECHAT_OFFICIAL_APP_SECRET),
        "已配置" if settings.WECHAT_OFFICIAL_APP_ID and settings.WECHAT_OFFICIAL_APP_SECRET else "未配置")
    wecom_ok = bool(settings.WECOM_CORP_ID and settings.WECOM_CONTACT_SECRET and settings.WECOM_TOKEN and settings.WECOM_ENCODING_AES_KEY)
    add("企业微信通道", wecom_ok, "已配置" if wecom_ok else "未配置（预留）")

    try:
        from core.redis_session import get_sync_redis
        redis = get_sync_redis()
        if redis is not None:
            add("Redis", True, "已启用（高并发/会话共享）")
        else:
            add("Redis", True, "未配置，使用内存模式（预留降级）")
    except Exception as e:
        add("Redis", False, str(e)[:120])

    try:
        from core.object_storage import remote_status
        info = remote_status()
        if info["configured"]:
            add("对象存储", True, f"{info['provider']} / {info['bucket']}")
        else:
            add("对象存储", True, "未配置远程，备份归档到本地 object_store")
    except Exception as e:
        add("对象存储", False, str(e)[:120])

    try:
        from core.monitor import monitor
        s = monitor.summary(300)
        add("运行监控", True,
            f"近5分钟 {s['total_requests']} 请求，错误 {s['error_count']} 次，P95 {s['p95_latency_ms']}ms")
    except Exception as e:
        add("运行监控", False, str(e)[:120])

    try:
        from core.backup import last_backup
        info = last_backup()
        add("数据备份", info["exists"],
            f"最近备份 {info['last']}，共 {info['count']} 份" if info["exists"] else "还没有备份")
    except Exception as e:
        add("数据备份", False, str(e)[:120])

    return {
        "ok": all(c["ok"] for c in checks),
        "checks": checks,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


@router.get("/system/release-readiness", dependencies=[Depends(require_admin)])
async def release_readiness(request: Request):
    checks = []

    def add(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)})

    try:
        from core.db import schema_revision
        revision = schema_revision()
        add("数据库迁移", bool(revision), revision or "未纳管")
    except Exception as exc:
        add("数据库迁移", False, str(exc)[:160])

    package_path = Path(__file__).resolve().parent.parent / "desktop-client" / "package.json"
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
        add("客户端版本", True, package.get("version") or "未知")
    except Exception as exc:
        add("客户端版本", False, str(exc)[:160])

    try:
        from wechat_bridge.run import BRIDGE_AGENT_VERSION
        add("桥接版本", True, BRIDGE_AGENT_VERSION)
    except Exception as exc:
        add("桥接版本", False, str(exc)[:160])

    try:
        from core.vector_store import KnowledgeStore
        store = KnowledgeStore(tenant_id=current_tenant(request))
        add("知识库后端", True, store.backend_name)
    except Exception as exc:
        add("知识库后端", False, str(exc)[:160])

    add(
        "支付回调签名",
        bool(settings.PAYMENT_WEBHOOK_SECRET),
        "已配置" if settings.PAYMENT_WEBHOOK_SECRET else "未配置，正式环境会拒绝回调",
    )
    add(
        "安装包签名",
        False,
        "请在发布流水线执行 scripts/verify_release.py --require-signed",
    )
    return {
        "ok": all(item["ok"] for item in checks if item["name"] != "安装包签名"),
        "checks": checks,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


@router.get("/system/onboarding", dependencies=[Depends(require_admin)])
async def onboarding():
    from core import sql_compat as sqlite3  # SQL 统一指向 DATABASE_URL，避免与 ORM 分叉
    from pathlib import Path
    from knowledge.knowledge_manager import KnowledgeManager
    db = Path(settings.DATA_DIR) / "customers.db"
    # 不再用 db.exists() 短路：SQL 已经统一走 DATABASE_URL，正式环境（PG）本地根本没有这个文件，
    # 一旦短路就会把所有检查项静默算成 0，引导页会永远显示"未完成"。
    conn = sqlite3.connect(str(db))
    def count(sql):
        try:
            row = conn.execute(sql).fetchone()
            return (row[0] or 0) if row else 0
        except Exception:
            return 0
    items = [
        {"key": "product", "label": "产品信息", "ok": count("SELECT COUNT(*) FROM product_knowledge WHERE active=1") > 0,
         "detail": "在 话术弹药库-产品知识 配置课程信息"},
        {"key": "knowledge", "label": "知识库投喂", "ok": count("SELECT COUNT(*) FROM knowledge_versions WHERE status='approved'") > 0 or len(KnowledgeManager().list_knowledge_files()) > 0,
         "detail": "上传课程/FAQ 并审批重建"},
        {"key": "ammo", "label": "话术弹药库", "ok": count("SELECT COUNT(*) FROM product_knowledge") + count("SELECT COUNT(*) FROM followup_scripts") > 0,
         "detail": "补充产品知识、异议应答、跟进话术"},
        {"key": "official", "label": "公众号通道", "ok": bool(settings.WECHAT_OFFICIAL_APP_ID and settings.WECHAT_OFFICIAL_APP_SECRET), "detail": "配置公众号 AppID/Secret"},
        {"key": "payment", "label": "付款交付", "ok": count("SELECT COUNT(*) FROM payment_links WHERE status='active'") > 0, "detail": "配置付款链接与交付话术"},
        {"key": "admin", "label": "管理员账号", "ok": count("SELECT COUNT(*) FROM system_users WHERE role IN ('admin','manager')") > 0, "detail": "在 企业运营-账号管理 创建管理员"},
        {"key": "backup", "label": "数据备份", "ok": len(list((Path(settings.DATA_DIR) / 'backups').glob('backup-*'))) > 0 if (Path(settings.DATA_DIR) / 'backups').exists() else False, "detail": "执行一次备份"},
    ]
    if conn:
        conn.close()
    done = sum(1 for i in items if i["ok"])
    return {"items": items, "done": done, "total": len(items)}


@router.get("/system/llm-router")
async def router_status():
    from core.llm_router import llm_router
    return llm_router.status()


@router.post("/system/llm-router", dependencies=[Depends(require_admin)])
async def router_switch(req: RouterSwitch):
    from core.llm_router import llm_router
    ok = llm_router.switch(req.model)
    return {"ok": ok, "status": llm_router.status()}


@router.get("/system/llm-traces")
async def llm_traces(session_id: str = Query(""), limit: int = Query(100, le=500)):
    from core.llm_trace import llm_trace_manager
    return {"summary": llm_trace_manager.summary(), "traces": llm_trace_manager.list(session_id=session_id, limit=limit)}


@router.post("/system/backup/remote", dependencies=[Depends(require_admin)])
async def backup_remote():
    from core.backup import archive_backup
    return archive_backup()


@router.post("/system/backup", dependencies=[Depends(require_admin)])
async def manual_backup():
    from core.backup import backup_data
    result = backup_data()
    logger.info("手动数据备份完成: %s", result["dir"])
    return result
