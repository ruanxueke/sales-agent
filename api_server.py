"""AI API 服务 - 供 Wechaty bot.js 调用的 HTTP 接口"""
import logging
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from config.settings import settings
from api.audit import router as audit_router
from api.ammo import router as ammo_router
from api.aiops import router as aiops_router
from api.accounts import router as accounts_router
from api.compliance_flow import router as compliance_flow_router
from api.approval_rules import router as approval_rules_router
from api.performance import router as performance_router
from api.service_policies import router as service_policies_router
from api.chat import router as chat_router
from api.compliance import router as compliance_router
from api.conversation import router as conversation_router
from api.cpq import router as cpq_router
from api.crm import router as crm_router
from api.channels import router as channels_router
from api.engagement import router as engagement_router
from api.export import router as export_router
from api.feedback import router as feedback_router
from api.tracing import router as tracing_router
from api.finance import router as finance_router
from api.followup import router as followup_router
from api.handover import router as handover_router
from api.knowledge import router as knowledge_router
from api.lead import router as lead_router
from api.marketing import router as marketing_router
from api.monitor import router as monitor_router
from api.optimization import router as optimization_router
from api.nurture import router as nurture_router
from api.official import router as official_router
from api.opportunity import router as opportunity_router
from api.order import router as order_router
from api.payment import router as payment_router
from api.platform import router as platform_router
from api.portrait import router as portrait_router
from api.prompt import router as prompt_router
from api.quality import router as quality_router
from api.reports import router as reports_router
from api.scoring import router as scoring_router
from api.security import router as security_router
from api.sop import router as sop_router
from api.system_check import router as system_check_router
from api.ticket import router as ticket_router
from api.winning import router as winning_router
from api.usage import router as usage_router
from api.voice import router as voice_router
from api.optimize import router as optimize_router
from api.tenant import router as tenant_router
from api.billing import router as billing_router
from api.analytics import router as analytics_router
from api.ai_capabilities import router as ai_capabilities_router
from api.webchat import router as webchat_router
from api.integrations import router as integrations_router
from api.registration import router as registration_router
from api.image import router as image_router
from api.org import router as org_router
from api.public_webchat import router as public_webchat_router
from api.alerting import router as alerting_router
from api.customer_success import router as customer_success_router
from api.business_intelligence import router as business_intelligence_router
from api.sales_flow import router as sales_flow_router
from api.commercial import router as commercial_router
from api.vision import router as vision_router
from api.personal_wechat import router as personal_wechat_router
from api.concurrency_check import router as concurrency_check_router
from api.license import router as license_router
from connectors.wecom import router as wecom_router
from connectors.wecom import admin_router as wecom_admin_router
from core.monitor import monitor

LOG_FILE = Path(__file__).resolve().parent / "api_server.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)

app = FastAPI(
    title="销售客服智能体 - AI API",
    # 默认不暴露接口文档：/docs、/redoc、/openapi.json 会把完整接口清单与参数结构
    # 公开给任何人。需要时用 ENABLE_API_DOCS=true 打开（仅限本地开发）。
    docs_url="/docs" if settings.ENABLE_API_DOCS else None,
    redoc_url="/redoc" if settings.ENABLE_API_DOCS else None,
    openapi_url="/openapi.json" if settings.ENABLE_API_DOCS else None,
)
app.include_router(audit_router)
app.include_router(ammo_router)
app.include_router(aiops_router)
app.include_router(accounts_router)
app.include_router(compliance_flow_router)
app.include_router(approval_rules_router)
app.include_router(performance_router)
app.include_router(service_policies_router)
app.include_router(chat_router)
app.include_router(compliance_router)
app.include_router(conversation_router)
app.include_router(cpq_router)
app.include_router(crm_router)
app.include_router(channels_router)
app.include_router(engagement_router)
app.include_router(export_router)
app.include_router(feedback_router)
app.include_router(tracing_router)
app.include_router(finance_router)
app.include_router(followup_router)
app.include_router(handover_router)
app.include_router(knowledge_router)
app.include_router(lead_router)
app.include_router(marketing_router)
app.include_router(monitor_router)
app.include_router(optimization_router)
app.include_router(nurture_router)
app.include_router(official_router)
app.include_router(opportunity_router)
app.include_router(order_router)
app.include_router(payment_router)
app.include_router(platform_router)
app.include_router(portrait_router)
app.include_router(prompt_router)
app.include_router(quality_router)
app.include_router(reports_router)
app.include_router(scoring_router)
app.include_router(security_router)
app.include_router(wecom_router)
app.include_router(wecom_admin_router)
app.include_router(sop_router)
app.include_router(system_check_router)
app.include_router(ticket_router)
app.include_router(winning_router)
app.include_router(usage_router)
app.include_router(voice_router)
app.include_router(optimize_router)
app.include_router(tenant_router)
app.include_router(billing_router)
app.include_router(analytics_router)
app.include_router(ai_capabilities_router)
app.include_router(webchat_router)
app.include_router(integrations_router)
app.include_router(registration_router)
app.include_router(image_router)
app.include_router(org_router)
app.include_router(public_webchat_router)
app.include_router(alerting_router)
app.include_router(customer_success_router)
app.include_router(business_intelligence_router)
app.include_router(sales_flow_router)
app.include_router(commercial_router)
app.include_router(vision_router)
app.include_router(personal_wechat_router)
app.include_router(concurrency_check_router)
app.include_router(license_router)

from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# 控制台是单文件页面（static/console.html），内联 <script>、内联样式与 Google Fonts
# 都依赖，因此 script-src/style-src 必须保留 'unsafe-inline'，font-src 要放行 gstatic。
# 关键收益在于：把 default-src 收成 'self' 后，任何外域脚本、外域 fetch、外域表单提交
# 与 <base> 改写都会被浏览器拦下 —— 原来的 CSP 只有 frame-ancestors，
# 等于对 XSS 没有任何脚本级防护（见清单 B3）。
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com data:",
    "img-src 'self' data: blob:",
    "connect-src 'self' ws: wss:",
    "form-action 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors 'self'",
])


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    response.headers["Referrer-Policy"] = "no-referrer"
    # 不再下发 X-XSS-Protection：该头已被所有主流浏览器废弃，
    # 保留旧值（1; mode=block）在个别老浏览器上反而会引入自身的问题。
    return response


@app.middleware("http")
async def api_auth_middleware(request: Request, call_next):
    exempt = (
        "/api/v1/payment/",
        "/api/v1/auth/login",
        # 自助注册必须免鉴权，否则"开通试用"这个入口直接被 401 打死：
        # 用户手上还没有任何 API Key，却要先通过 API Key 校验才能注册。
        "/api/v1/auth/register",
        "/api/v1/registration/register",
        "/api/v1/compliance/deletion-request",
        "/api/v1/compliance/status",
        "/public/",
    )
    if request.url.path.startswith("/api/") and not any(request.url.path.startswith(p) for p in exempt):
        from core.security import (
            authenticate_credential,
            configured_api_keys,
            extract_api_key,
            mask_key,
            client_ip,
        )
        from core.rbac import has_permission, required_permission_for_request
        keys = configured_api_keys()
        if keys:
            key = extract_api_key(request)
            actor = authenticate_credential(key)
            if actor.get("kind") == "anonymous":
                from core.audit import audit
                audit(
                    # 只记脱敏后的 Key：原来把请求里带的密钥原样落库，
                    # 审计表一旦被读走就等于泄漏凭据（见清单 B4）。
                    actor=mask_key(key) if key else "anonymous",
                    action="auth_fail",
                    resource=request.url.path,
                    # 取真实客户端 IP：直接在 nginx 后面取 request.client.host 的话，
                    # 审计里所有记录都会是同一个反代地址。
                    ip=client_ip(request),
                )
                return JSONResponse(status_code=401, content={"detail": "无效的 API Key"})
            required = required_permission_for_request(
                request.url.path,
                request.method,
            )
            if required and not has_permission(
                actor.get("role") or "",
                required,
                actor.get("scopes") or [],
            ):
                from core.audit import audit
                audit(
                    actor=mask_key(key),
                    action="permission_denied",
                    resource=request.url.path,
                    detail=f"required={required}",
                    ip=client_ip(request),
                )
                return JSONResponse(
                    status_code=403,
                    content={"detail": f"缺少权限：{required}"},
                )
            request.state.actor = actor
            from core.tenant_context import tenant_scope

            tenant_id = actor.get("tenant_id")
            with tenant_scope(
                int(tenant_id) if tenant_id is not None else None,
                disable_filter=tenant_id is None,
            ):
                return await call_next(request)
    return await call_next(request)


@app.middleware("http")
async def monitor_middleware(request: Request, call_next):
    start = time.perf_counter()
    success = True
    try:
        response = await call_next(request)
        success = response.status_code < 500
        return response
    except Exception:
        success = False
        raise
    finally:
        if request.url.path.startswith("/api/"):
            monitor.record_api_event(
                request.url.path,
                int((time.perf_counter() - start) * 1000),
                success,
            )


@app.websocket("/ws/notifications")
async def ws_notifications(websocket: WebSocket, token: str = "", key: str = ""):
    """实时通知 WebSocket。

    原来这个端点是**完全无鉴权**的：任何人连上就能收到全部广播（见清单 B2）。
    浏览器 WebSocket 无法自定义请求头，因此凭据通过查询参数传入：
        /ws/notifications?token=<登录令牌>    或    ?key=<API Key>
    握手阶段校验，失败直接以 4401 关闭，不入 hub。
    """
    from core.realtime import hub
    from core.security import authenticate_credential, mask_key

    credential = (token or key or "").strip()
    actor = authenticate_credential(credential)
    if actor["kind"] == "anonymous":
        await websocket.close(code=4401)
        return

    await websocket.accept()
    # tenant_id=None 表示跨租户视角（超管 Key），能收到所有租户通知
    await hub.connect(websocket, tenant_id=actor["tenant_id"], actor=mask_key(credential))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await hub.disconnect(websocket)
    except Exception:
        await hub.disconnect(websocket)


@app.get("/health")
async def health():
    """探活端点：只返回存活状态。

    原实现会把 `check_db_health()` 的完整结果（含异常字符串）直接返回，
    而 SQLAlchemy 的连接失败信息里可能带完整 DSN（含口令），
    且这个端点不需要鉴权（见清单 B2）。
    详细指标改到需鉴权的 /api/v1/aiops/health。
    """
    if settings.HEALTH_EXPOSE_DETAIL:
        from core.db import check_db_health
        return {"status": "ok", "service": "ai-api", "database": check_db_health()}
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    from core.db import check_db_health

    database = check_db_health()
    database_ok = database.get("status") == "ok"
    migration_ok = True
    if not getattr(settings, "AUTO_CREATE_TABLES", True):
        migration_ok = (
            database.get("schema_revision")
            == "0009_reply_reliability"
        )

    redis_ok = True
    redis_required = bool(getattr(settings, "REDIS_URL", ""))
    if redis_required:
        try:
            from core.redis_session import get_sync_redis

            client = get_sync_redis()
            redis_ok = bool(client and client.ping())
        except Exception:
            redis_ok = False

    payload = {
        "status": "ready" if database_ok and migration_ok and redis_ok else "not_ready",
        "database": database_ok,
        "migration": migration_ok,
        "redis": redis_ok,
        "schema_revision": database.get("schema_revision") or "",
    }
    return JSONResponse(
        status_code=200 if payload["status"] == "ready" else 503,
        content=payload,
    )


if __name__ == "__main__":
    # 定时任务已迁移至 Celery Beat（core/tasks.py），不再使用内置 scheduler
    workers = getattr(__import__("config.settings", fromlist=["settings"]).settings, "UVICORN_WORKERS", 1)
    uvicorn.run("api_server:app", host="0.0.0.0", port=5000, reload=False, workers=workers)
