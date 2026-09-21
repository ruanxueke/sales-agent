"""企业级能力测试：订单、自动跟进、行为评分、质检、导出、幂等、审计"""
from __future__ import annotations
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_tmp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
_tmp_db.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"

import config.settings as cfg
cfg.settings.API_KEYS = ""
cfg.settings.ADMIN_API_KEYS = ""

from fastapi.testclient import TestClient
from api_server import app

client = TestClient(app)
checks = []


def check(name: str, cond: bool, detail: str = ""):
    assert cond, f"{name}: {detail}"
    checks.append(name)
    print(f"  {name} [OK]")


print("=" * 60)
print("销售客服智能体 - 企业级能力测试")
print("=" * 60)

print("\n--- 测试1: 成交闭环 ---")
r = client.post("/api/v1/orders", json={
    "customer_name": "订单客户",
    "phone": "13911110001",
    "product_name": "AI副业实战课",
    "amount": 2999,
})
check("order-create", r.status_code == 200 and r.json()["order"]["order_no"])
order_id = r.json()["order"]["id"]
r = client.post(f"/api/v1/orders/{order_id}/pay", json={"method": "wechat"})
check("order-pay", r.status_code == 200 and r.json()["order"]["status"] == "paid")
r = client.get("/api/v1/orders/stats")
check("order-stats", r.json()["paid_orders"] == 1)

print("\n--- 测试2: 动态意向评分 ---")
r = client.post("/api/v1/behavior", json={"session_id": "behavior_user", "event_type": "quote_view"})
check("behavior", r.status_code == 200 and r.json()["weight"] == 8)
r = client.get("/api/v1/behavior/stats")
check("behavior-stats", r.json()["total_events"] == 1)

print("\n--- 测试3: 自动跟进 ---")
r = client.post("/api/v1/followups/plan", json={"session_id": "behavior_user"})
check("followup-plan", r.status_code == 200 and "created" in r.json())
r = client.get("/api/v1/followups/tasks")
check("followup-tasks", r.status_code == 200)

print("\n--- 测试4: 质检与导出 ---")
r = client.post("/api/v1/quality/check", json={"session_id": "behavior_user"})
check("quality-check", r.status_code == 200)
r = client.get("/api/v1/export/leads.csv")
check("export", r.status_code == 200 and r.headers["content-type"].startswith("text/csv"))
r = client.get("/api/v1/audit")
check("audit", r.status_code == 200 and isinstance(r.json()["logs"], list))

print("\n--- 测试5: 消息幂等 ---")
from core.idempotency import idempotency_store
first = idempotency_store.mark("dup-msg-001", "official")
second = idempotency_store.mark("dup-msg-001", "official")
check("idempotency", first is True and second is False)

from core.db import engine
engine.dispose()
try:
    os.unlink(_tmp_db.name)
except OSError:
    pass
print("\n" + "=" * 60)
print(f"企业级能力测试全部通过: {len(checks)} 项")
print("=" * 60)
