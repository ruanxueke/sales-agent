"""新增业务模块自测：商机、CPQ、回款、画像、SOP、工单、营销、培育、平台"""
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
print("新增业务模块自测")
print("=" * 60)

print("\n--- 商机管理 ---")
r = client.post("/api/v1/opportunities", json={
    "name": "测试商机", "session_id": "biz-test", "product_name": "AI变现课",
    "amount": 4999, "stage": "qualifying", "owner": "叙白",
})
opp = r.json()["opportunity"]
check("opportunity-create", r.status_code == 200 and opp["id"])
r = client.post(f"/api/v1/opportunities/{opp['id']}/stage", json={"stage": "proposal"})
check("opportunity-stage", r.json()["opportunity"]["stage"] == "proposal")
r = client.post(f"/api/v1/opportunities/{opp['id']}/predict", json={})
check("opportunity-predict", r.json()["opportunity"]["predicted_win_rate"] >= 0)
r = client.get("/api/v1/opportunities/stats")
check("opportunity-stats", r.json()["pipeline"] >= 0)

print("\n--- 报价合同 CPQ ---")
r = client.post("/api/v1/price-items", json={"product_name": "AI变现课", "price": 4999, "sku": "AI-01"})
check("price-item-create", r.status_code == 200)
r = client.post("/api/v1/quotes", json={
    "customer_name": "测试客户", "product_name": "AI变现课",
    "base_amount": 4999, "discount_rate": 10, "session_id": "biz-test",
})
quote = r.json()["quote"]
check("quote-create", r.status_code == 200 and quote["total_amount"] > 0)
r = client.post(f"/api/v1/quotes/{quote['id']}/status", json={"status": "approved", "approver": "叙白"})
check("quote-approve", r.json()["quote"]["status"] == "approved")
r = client.post("/api/v1/contracts", json={
    "quote_id": quote["id"], "customer_name": "测试客户", "product_name": "AI变现课",
    "amount": quote["total_amount"], "terms": "7天试用", "session_id": "biz-test",
})
contract = r.json()["contract"]
check("contract-create", r.status_code == 200 and contract["contract_no"])
r = client.post(f"/api/v1/contracts/{contract['id']}/status", json={"status": "signed"})
check("contract-sign", r.json()["contract"]["status"] == "signed")
r = client.get("/api/v1/cpq/stats")
check("cpq-stats", r.json()["quotes"] >= 1)

print("\n--- 回款与 L2C ---")
r = client.post("/api/v1/orders", json={
    "customer_name": "回款客户", "product_name": "AI变现课", "amount": 4499, "session_id": "biz-test",
})
order_id = r.json()["order"]["id"]
r = client.post("/api/v1/shipments", json={"order_id": order_id, "carrier": "顺丰"})
shipment_id = r.json()["shipment"]["id"]
check("shipment-create", r.status_code == 200)
r = client.patch(f"/api/v1/shipments/{shipment_id}", json={"status": "shipped"})
check("shipment-ship", r.json()["shipment"]["status"] == "shipped")
r = client.post("/api/v1/invoices", json={"order_id": order_id, "amount": 4499, "title": "测试公司"})
invoice_id = r.json()["invoice"]["id"]
check("invoice-create", r.status_code == 200)
r = client.post(f"/api/v1/invoices/{invoice_id}/status", json={"status": "issued"})
check("invoice-issue", r.json()["invoice"]["status"] == "issued")
r = client.post("/api/v1/payment-plans", json={
    "order_id": order_id, "amounts": [2249.5, 2249.5],
    "due_dates": ["2026-08-10 10:00:00", "2026-08-20 10:00:00"],
})
check("payment-plans", len(r.json()["plans"]) == 2)
receivable_id = client.get("/api/v1/receivables").json()["receivables"][0]["id"]
r = client.post(f"/api/v1/receivables/{receivable_id}/receipt", json={"amount": 2249.5, "method": "wechat"})
check("receipt", r.json()["receivable"]["received_amount"] > 0)
r = client.get("/api/v1/finance/stats")
check("finance-stats", r.status_code == 200)

print("\n--- 客户360画像 ---")
r = client.post("/api/v1/portrait/business-profile", json={"session_id": "biz-test", "company_name": "测试科技"})
check("business-profile", r.status_code == 200)
r = client.post("/api/v1/portrait/stakeholders", json={"session_id": "biz-test", "name": "李总", "role": "决策人"})
check("stakeholder", r.status_code == 200)
r = client.post("/api/v1/portrait/tags", json={"session_id": "biz-test", "tag": "高意向"})
check("tag", r.status_code == 200)
r = client.get("/api/v1/portrait", params={"session_id": "biz-test"})
check("portrait", r.status_code == 200 and len(r.json()["tags"]) >= 1)

print("\n--- 销售SOP ---")
r = client.post("/api/v1/sop/templates", json={
    "name": "跟进SOP", "stage": "proposal",
    "steps": [{"name": "发送方案", "due_hours": 2}, {"name": "确认反馈", "due_hours": 24}],
})
template = r.json()["template"]
check("sop-template", r.status_code == 200 and len(template["steps"]) == 2)
r = client.post("/api/v1/sop/executions", json={"template_id": template["id"], "session_id": "biz-test"})
check("sop-execution", r.json()["created"] == 2)
execution_id = client.get("/api/v1/sop/executions").json()["executions"][0]["id"]
r = client.post(f"/api/v1/sop/executions/{execution_id}/complete", json={})
check("sop-complete", r.json()["execution"]["status"] == "done")

print("\n--- 工单与回访 ---")
r = client.post("/api/v1/tickets", json={"title": "发票问题", "session_id": "biz-test", "priority": "high"})
ticket = r.json()["ticket"]
check("ticket-create", r.status_code == 200 and ticket["sla_due_at"])
r = client.patch(f"/api/v1/tickets/{ticket['id']}", json={"status": "resolved"})
check("ticket-resolve", r.json()["ticket"]["status"] == "resolved")
r = client.post("/api/v1/visits", json={"session_id": "biz-test", "content": "确认体验", "visit_type": "followup"})
check("visit-create", r.status_code == 200)
r = client.get("/api/v1/tickets/stats")
check("ticket-stats", r.status_code == 200)

print("\n--- 营销与复购 ---")
r = client.post("/api/v1/campaigns", json={"name": "618活动", "channel": "official", "budget": 10000})
campaign = r.json()["campaign"]
check("campaign-create", r.status_code == 200)
r = client.post("/api/v1/ad-metrics", json={
    "campaign_id": campaign["id"], "metric_date": "2026-08-06",
    "impressions": 10000, "clicks": 500, "conversions": 20, "cost": 2000, "revenue": 8000,
})
check("ad-metric", r.json()["metric"]["roi"] > 0)
r = client.post("/api/v1/repurchases", json={
    "session_id": "biz-test", "product_name": "进阶课", "plan_date": "2026-08-10 10:00:00",
})
check("repurchase-create", r.status_code == 200)
r = client.get("/api/v1/marketing/stats")
check("marketing-stats", r.status_code == 200)

print("\n--- 培育计划 ---")
r = client.post("/api/v1/nurture/campaigns", json={
    "name": "意向培育", "trigger_type": "stage", "trigger_value": "recommended",
})
campaign_id = r.json()["campaign"]["id"]
check("nurture-campaign", r.status_code == 200)
r = client.post("/api/v1/nurture/rules", json={
    "campaign_id": campaign_id, "sequence": 1, "content": "您好{nickname}",
    "condition_type": "always", "delay_hours": 0,
})
check("nurture-rule", r.status_code == 200)
r = client.get("/api/v1/nurture/stats")
check("nurture-stats", r.json()["rules"] >= 1)

print("\n--- 平台化 ---")
r = client.post("/api/v1/custom-fields", json={
    "entity": "customer", "field_name": "行业", "field_key": "industry_custom", "field_type": "text",
})
check("custom-field", r.status_code == 200)
r = client.post("/api/v1/roles", json={"name": "销售主管", "permissions": ["opportunity:write"]})
check("role-create", r.status_code == 200)
r = client.post("/api/v1/team", json={"name": "小王", "nickname": "小王", "role": "sales"})
check("team-create", r.status_code == 200)
r = client.get("/api/v1/bi/metrics")
check("bi-metrics", r.status_code == 200 and len(r.json()["funnel"]) > 0)

print("\n" + "=" * 60)
print(f"新增业务模块自测全部通过: {len(checks)} 项")
print("=" * 60)
