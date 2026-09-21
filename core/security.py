"""接口安全：API Key 鉴权、租户归属与管理员权限

租户模型（修正说明）：
旧版规则是「API Key 身份 = 租户 None = 看全部」。但本机桥接、桌面控制台都是
用 API Key 鉴权的，于是租户过滤在个人微信链路上被整体跳过：claim/ack/status
会跨租户命中，心跳与「开始识别」永远落在 tenant 0。

现在的规则是「凭据即租户」：
- token 身份 → 用户所属 tenant_id
- api_key 身份 → 由 API_KEY_TENANTS 映射得到；未映射则落 DEFAULT_TENANT_ID
- 只有显式列入 SUPER_ADMIN_API_KEYS 的 Key 才拥有跨租户视角，
  并且必须通过 current_tenant_filter() 显式索取，避免默认漏掉租户条件。
"""
from __future__ import annotations

from fastapi import HTTPException, Request

from config.settings import settings
from core.audit import audit
import logging
logger = logging.getLogger(__name__)



def _split(raw: str) -> list[str]:
    return [k.strip() for k in (raw or "").split(",") if k.strip()]


def _resolve(raw: str) -> str:
    from core.secrets import resolve
    return resolve(raw).strip()


def mask_key(key: str) -> str:
    """日志与审计里只保留前缀，避免把完整密钥写进库。"""
    key = key or ""
    if not key:
        return "anonymous"
    if len(key) <= 8:
        return key[:2] + "***"
    return key[:6] + "***" + key[-2:]


def configured_api_keys() -> list[str]:
    return [_resolve(k) for k in _split(settings.API_KEYS) if _resolve(k)]


def configured_admin_keys() -> list[str]:
    return [_resolve(k) for k in _split(settings.ADMIN_API_KEYS) if _resolve(k)]


def configured_super_admin_keys() -> list[str]:
    return [_resolve(k) for k in _split(getattr(settings, "SUPER_ADMIN_API_KEYS", "")) if _resolve(k)]


def api_key_tenant_map() -> dict[str, int]:
    """解析 API_KEY_TENANTS（key=租户ID，逗号分隔）。"""
    mapping: dict[str, int] = {}
    for item in _split(getattr(settings, "API_KEY_TENANTS", "")):
        if "=" not in item:
            continue
        raw_key, _, raw_tenant = item.partition("=")
        key = _resolve(raw_key.strip())
        try:
            tenant_id = int(raw_tenant.strip())
        except ValueError:
            continue
        if key:
            mapping[key] = tenant_id
    return mapping


def default_tenant_id() -> int:
    try:
        return int(getattr(settings, "DEFAULT_TENANT_ID", 0) or 0)
    except (TypeError, ValueError):
        return 0


def extract_api_key(request: Request) -> str:
    key = request.headers.get("X-API-Key") or ""
    if not key:
        auth = request.headers.get("Authorization") or ""
        if auth.startswith("Bearer "):
            key = auth[7:].strip()
    return key


def client_ip(request: Request) -> str:
    """取真实客户端 IP。

    生产在 nginx 后面，`request.client.host` 只会是反代地址（审计日志与登录限流都会
    因此把所有请求算成同一个来源）。优先信任 `X-Forwarded-For` 的第一跳。
    """
    try:
        fwd = request.headers.get("x-forwarded-for") or ""
        if fwd:
            return fwd.split(",")[0].strip()
        real = request.headers.get("x-real-ip") or ""
        if real:
            return real.strip()
        return (request.client.host if request.client else "") or ""
    except Exception:
        return ""


def current_actor(request: Request) -> dict:
    """返回 {kind: api_key|service_key|token|anonymous, key, user, tenant_id, role, scopes}"""
    key = extract_api_key(request)
    if key and key in configured_api_keys():
        if key in configured_super_admin_keys():
            role = "super_admin"
            tenant_id = None
        elif key in configured_admin_keys():
            role = "admin"
            tenant_id = api_key_tenant_map().get(key, default_tenant_id())
        else:
            role = "service"
            tenant_id = api_key_tenant_map().get(key, default_tenant_id())
        from core.rbac import DEFAULT_API_KEY_SCOPES
        return {
            "kind": "api_key",
            "key": key,
            "user": None,
            "tenant_id": tenant_id,
            "role": role,
            "scopes": (
                sorted(DEFAULT_API_KEY_SCOPES)
                if role == "service"
                else ["*"]
            ),
        }
    if key:
        try:
            from core.rbac import authenticate_service_key
            account = authenticate_service_key(key)
            if account:
                return {
                    "kind": "service_key",
                    "key": key,
                    "user": None,
                    "service_account": account,
                    "tenant_id": int(account.get("tenant_id") or default_tenant_id()),
                    "role": account.get("role") or "service",
                    "scopes": account.get("scopes") or [],
                }
        except Exception as e:
            logger.warning("服务账号 Key 校验失败，按匿名处理: %s", e)
    if key:
        try:
            from core.enterprise import enterprise
            user = enterprise.get_user_by_token(key)
            if user:
                return {
                    "kind": "token",
                    "key": key,
                    "user": user,
                    "tenant_id": int(user.get("tenant_id") or default_tenant_id()),
                    "role": str(user.get("role") or "sales"),
                    "scopes": [],
                }
        except Exception as e:
            logger.warning("凭据换用户失败，按匿名处理: %s", e)
    return {
        "kind": "anonymous",
        "key": key,
        "user": None,
        "tenant_id": None,
        "role": "",
        "scopes": [],
    }


def auth_required() -> bool:
    """是否已配置 API Key（未配置时为本地开发模式，不做校验）。"""
    return bool(configured_api_keys())


def authenticate_credential(key: str) -> dict:
    """不依赖 Request 的凭据校验，供 WebSocket 握手等场景使用。

    返回值：{kind, key, user, tenant_id}
    - kind == "anonymous" 表示校验失败
    - 未配置任何 API Key（本地开发）时，任何凭据都视为通过，租户取默认值
    """
    key = (key or "").strip()
    keys = configured_api_keys()
    if not keys:
        return {
            "kind": "local",
            "key": key,
            "user": None,
            "tenant_id": default_tenant_id(),
            "role": "owner",
            "scopes": ["*"],
        }

    if key in keys:
        if key in configured_super_admin_keys():
            role = "super_admin"
            tenant_id = None
        elif key in configured_admin_keys():
            role = "admin"
            tenant_id = api_key_tenant_map().get(key, default_tenant_id())
        else:
            role = "service"
            tenant_id = api_key_tenant_map().get(key, default_tenant_id())
        from core.rbac import DEFAULT_API_KEY_SCOPES
        return {
            "kind": "api_key",
            "key": key,
            "user": None,
            "tenant_id": tenant_id,
            "role": role,
            "scopes": (
                sorted(DEFAULT_API_KEY_SCOPES)
                if role == "service"
                else ["*"]
            ),
        }
    try:
        from core.rbac import authenticate_service_key

        account = authenticate_service_key(key)
        if account:
            return {
                "kind": "service_key",
                "key": key,
                "user": None,
                "service_account": account,
                "tenant_id": int(account.get("tenant_id") or default_tenant_id()),
                "role": account.get("role") or "service",
                "scopes": account.get("scopes") or [],
            }
    except Exception as e:
        logger.warning("服务账号 Key 校验失败，按匿名处理: %s", e)
    if key:
        try:
            from core.enterprise import enterprise
            user = enterprise.get_user_by_token(key)
            if user:
                try:
                    tenant_id = int(user.get("tenant_id") or default_tenant_id())
                except (TypeError, ValueError):
                    tenant_id = default_tenant_id()
                return {
                    "kind": "token",
                    "key": key,
                    "user": user,
                    "tenant_id": tenant_id,
                    "role": str(user.get("role") or "sales"),
                    "scopes": [],
                }
        except Exception as e:
            logger.warning("凭据换用户失败，按匿名处理: %s", e)
    return {
        "kind": "anonymous",
        "key": key,
        "user": None,
        "tenant_id": None,
        "role": "",
        "scopes": [],
    }


def tenant_for_credential(key: str) -> int | None:
    """凭据 -> 租户；校验失败返回 None。

    超级管理员 Key 返回 None（跨租户视角），与 current_tenant_filter() 语义一致。
    """
    actor = authenticate_credential(key)
    if actor["kind"] == "anonymous":
        return None
    if actor.get("role") == "super_admin":
        return None
    return actor["tenant_id"]


def require_api_key(request: Request) -> str:
    keys = configured_api_keys()
    if not keys:
        return "local"
    actor = current_actor(request)
    if actor["kind"] in ("api_key", "service_key", "token"):
        return actor["key"]
    # 审计里只记录脱敏后的 Key 前缀
    audit(
        actor=mask_key(actor["key"]),
        action="auth_fail",
        resource=request.url.path,
        ip=request.client.host if request.client else "",
    )
    raise HTTPException(status_code=401, detail="无效的 API Key")


def current_tenant(request: Request) -> int:
    """返回当前请求的租户号（已鉴权请求一定是确定的整数，不会返回 None）。

    - token 身份：用户所属租户
    - api_key 身份：API_KEY_TENANTS 映射值，未映射则用 DEFAULT_TENANT_ID
    - 未配置任何 API Key（本地开发模式）：DEFAULT_TENANT_ID
    """
    actor = current_actor(request)
    if actor["kind"] in ("token", "service_key", "api_key"):
        try:
            value = actor.get("tenant_id")
            return default_tenant_id() if value is None else int(value)
        except (TypeError, ValueError):
            return default_tenant_id()
    return default_tenant_id()


def current_tenant_filter(request: Request) -> int | None:
    """返回租户过滤条件：None 表示跨租户（仅显式配置的超级管理员 Key）。

    只有需要跨租户聚合的运营/管理接口才应使用它；业务数据接口一律用
    current_tenant()，避免「默认看全部」这类横向越权。
    """
    actor = current_actor(request)
    if actor.get("role") == "super_admin":
        return None
    return current_tenant(request)


def require_admin(request: Request) -> str:
    key = require_api_key(request)
    keys = configured_api_keys()
    if not keys:
        return "local"
    actor = current_actor(request)
    if actor.get("role") in ("owner", "admin", "manager", "super_admin"):
        return key
    admins = configured_admin_keys()
    if key in admins:
        return key
    audit(
        actor=mask_key(key),
        action="admin_denied",
        resource=request.url.path,
        ip=request.client.host if request.client else "",
    )
    raise HTTPException(status_code=403, detail="需要管理员权限")


def require_permission(request: Request, required: str) -> dict:
    """按资源动作校验权限，供业务接口统一使用。"""
    key = require_api_key(request)
    keys = configured_api_keys()
    if not keys:
        return current_actor(request)
    actor = current_actor(request)
    from core.rbac import has_permission

    if has_permission(
        str(actor.get("role") or ""),
        required,
        actor.get("scopes") or [],
    ):
        return actor
    audit(
        actor=mask_key(key),
        action="permission_denied",
        resource=request.url.path,
        detail=f"required={required}",
        ip=request.client.host if request.client else "",
    )
    raise HTTPException(status_code=403, detail=f"缺少权限：{required}")


def permission_required(required: str):
    """FastAPI 依赖工厂：Depends(permission_required("customer:read"))。"""

    def dependency(request: Request) -> dict:
        return require_permission(request, required)

    return dependency
