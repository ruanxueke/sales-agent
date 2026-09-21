"""商用化加固自测：租户、权限、RAG、合规和支付回调。"""
from __future__ import annotations

import os
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_tmp_dir = tempfile.mkdtemp(prefix="sales-agent-hardening-")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_tmp_dir, "hardening.db")
os.environ["AUTO_CREATE_TABLES"] = "true"
os.environ["REDIS_URL"] = ""
os.environ["CACHE_REDIS_URL"] = ""
os.environ["RAG_BACKEND"] = "json"

import config.settings as cfg

cfg.settings.DATA_DIR = Path(_tmp_dir) / "data"
cfg.settings.KNOWLEDGE_BASE_DIR = cfg.settings.DATA_DIR / "knowledge_base"
cfg.settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
cfg.settings.KNOWLEDGE_BASE_DIR.mkdir(parents=True, exist_ok=True)
cfg.settings.API_KEYS = "sk-admin,sk-sales"
cfg.settings.ADMIN_API_KEYS = "sk-admin"
cfg.settings.API_KEY_TENANTS = "sk-admin=11,sk-sales=11"
cfg.settings.SUPER_ADMIN_API_KEYS = ""
cfg.settings.SECRET_KEY = "test-secret-key"
cfg.settings.PAYMENT_WEBHOOK_SECRET = ""
cfg.settings.ALLOW_UNSIGNED_PAYMENT_WEBHOOK = False
cfg.settings.RAG_BACKEND = "json"
cfg.settings.EMBEDDING_DIMENSION = 4

from fastapi.testclient import TestClient
from sqlalchemy import select

from api_server import app
from core.compliance_flow import compliance_flow
from core.db import init_db, session_scope
from core.models import Customer, CustomerChatLog, Notification
from core.rbac import (
    create_service_key,
    has_permission,
    revoke_service_key,
)
from core.sales_crm import crm
from core.tenant_context import all_tenants_scope, tenant_scope

checks: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    assert condition, f"{name}: {detail}"
    checks.append(name)
    print(f"  {name} [OK]")


class FakeEmbeddings:
    def _vector(self, text: str) -> list[float]:
        lowered = text.lower()
        return [
            1.0 if "alpha" in lowered else 0.0,
            1.0 if "beta" in lowered else 0.0,
            1.0 if "gamma" in lowered else 0.0,
            1.0 if "tenant" in lowered else 0.0,
        ]

    def embed_documents(self, texts):
        return [self._vector(text) for text in texts]

    def embed_query(self, text):
        return self._vector(text)


def main() -> int:
    init_db()
    print("=" * 60)
    print("商用化加固自测")
    print("=" * 60)

    print("\n--- 租户自动过滤 ---")
    customer_a = crm.get_or_create(
        "personal_wechat:11:wxid_a:customer_a",
        nickname="客户A",
        tenant_id=11,
    )
    customer_b = crm.get_or_create(
        "personal_wechat:12:wxid_b:customer_b",
        nickname="客户B",
        tenant_id=12,
    )
    with tenant_scope(11):
        visible = crm.list_customers()
    with tenant_scope(12):
        visible_b = crm.list_customers()
    with all_tenants_scope():
        all_rows = crm.list_customers()
    check("租户11只看到客户A", [row["id"] for row in visible] == [customer_a["id"]])
    check("租户12只看到客户B", [row["id"] for row in visible_b] == [customer_b["id"]])
    check("跨租户显式视角可看到两条", len(all_rows) == 2)

    print("\n--- 权限体系 ---")
    check("管理员拥有全部权限", has_permission("admin", "admin:access"))
    check("销售没有管理员权限", not has_permission("sales", "admin:access"))
    check("销售可以读取知识库", has_permission("sales", "knowledge:read"))

    client = TestClient(app)
    sales_headers = {"X-API-Key": "sk-sales"}
    admin_headers = {"X-API-Key": "sk-admin"}
    check(
        "销售访问审计接口返回403",
        client.get("/api/v1/audit", headers=sales_headers).status_code == 403,
    )
    me_response = client.get("/api/v1/accounts/me", headers=sales_headers)
    check(
        "销售可以读取自己的权限上下文",
        me_response.status_code == 200
        and me_response.json().get("role") == "service",
        str(me_response.json()),
    )
    check(
        "管理员访问审计接口返回200",
        client.get("/api/v1/audit", headers=admin_headers).status_code == 200,
    )

    print("\n--- 服务账号 Key ---")
    service = create_service_key(
        tenant_id=11,
        name="bridge",
        role="service",
        scopes=["customer:read", "channel:bridge"],
        created_by="test",
    )
    check("创建服务账号返回一次性密钥", service["key"].startswith("sak_"))
    check(
        "服务账号可读取客户",
        client.get(
            "/api/v1/customers",
            headers={"X-API-Key": service["key"]},
        ).status_code
        == 200,
    )
    check(
        "服务账号不能读取审计",
        client.get(
            "/api/v1/audit",
            headers={"X-API-Key": service["key"]},
        ).status_code
        == 403,
    )
    check("吊销服务账号成功", revoke_service_key(service["id"], tenant_id=11))
    check(
        "吊销后的服务账号被拒绝",
        client.get(
            "/api/v1/customers",
            headers={"X-API-Key": service["key"]},
        ).status_code
        == 401,
    )

    print("\n--- RAG 租户隔离 ---")
    import core.vector_store as vector_store_module
    from core.rag import RAGEngine

    vector_store_module.create_embeddings = lambda: FakeEmbeddings()
    from knowledge.knowledge_manager import KnowledgeManager

    KnowledgeManager(tenant_id=11).add_documents(
        [
            vector_store_module.Document(
                page_content="alpha tenant 11 knowledge",
                metadata={"source_filename": "a.txt"},
            )
        ]
    )
    KnowledgeManager(tenant_id=12).add_documents(
        [
            vector_store_module.Document(
                page_content="beta tenant 12 knowledge",
                metadata={"source_filename": "b.txt"},
            )
        ]
    )
    engine = RAGEngine()
    hits_11 = engine.query_with_scores("alpha", tenant_id=11)
    hits_12 = engine.query_with_scores("alpha", tenant_id=12)
    check("租户11能检索自己的知识", len(hits_11) == 1, str(hits_11))
    check(
        "租户12检索不到租户11知识",
        all("alpha tenant 11" not in item[0].page_content for item in hits_12),
        str(hits_12),
    )

    print("\n--- 合规删除 ---")
    crm.append_chat(customer_a["id"], "客户", "hello", tenant_id=11)
    crm.create_notification(
        customer_a["id"],
        target="sales",
        content="new lead",
        tenant_id=11,
    )
    request_row = compliance_flow.request_deletion(
        customer_a["session_id"],
        applicant="customer",
        reason="privacy",
        tenant_id=11,
    )
    deleted = compliance_flow.confirm_deletion(
        request_row["id"],
        handler="test",
        tenant_id=11,
    )
    check("租户11删除请求完成", deleted.get("ok") is True, str(deleted))
    check(
        "租户11客户数据已删除",
        crm.get_by_session(customer_a["session_id"], tenant_id=11) is None,
    )
    check(
        "租户12客户数据未受影响",
        crm.get_by_session(customer_b["session_id"], tenant_id=12) is not None,
    )
    with session_scope(read_only=True) as session:
        remaining_chat = session.execute(
            select(CustomerChatLog).where(
                CustomerChatLog.customer_id == customer_a["id"]
            )
        ).scalars().all()
        remaining_notifications = session.execute(
            select(Notification).where(
                Notification.customer_id == customer_a["id"]
            )
        ).scalars().all()
    check("客户聊天记录已清理", not remaining_chat)
    check("客户通知已清理", not remaining_notifications)

    print("\n--- 支付回调必须验签 ---")
    payment = client.post(
        "/api/v1/payment/webhook",
        json={"event": "paid", "order_id": 1},
    )
    check(
        "未配置密钥时拒绝未验签回调",
        payment.status_code == 200 and payment.json().get("ok") is False,
        str(payment.json()),
    )

    print("\n--- 发布版本与迁移链 ---")
    from scripts.verify_release import migration_head

    package = json.loads(
        (ROOT / "desktop-client" / "package.json").read_text(encoding="utf-8")
    )
    check("客户端版本已升级", package.get("version") == "1.0.11")
    check(
        "迁移头为商用加固版本",
        migration_head() == "0010_commercial_hardening",
        migration_head(),
    )

    print("\n" + "=" * 60)
    print(f"商用化加固自测通过：{len(checks)} 项")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
