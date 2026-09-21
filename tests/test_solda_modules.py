"""Solda 模式升级自测：弹药库、案例、会话摘要、赢单、预约优惠、优化、合规"""
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


def call(method, url, payload=None):
    r = client.request(method, url, json=payload)
    assert r.status_code == 200, (method, url, r.status_code, r.text[:300])
    return r.json()


print("=" * 60)
print("Solda 模式升级自测")
print("=" * 60)

print("\n--- 话术弹药库 ---")
r = call("GET", "/api/v1/ammo/products")
check("product-seed", len(r["products"]) >= 1 and r["products"][0]["price"] == "1980 元")
call("POST", "/api/v1/ammo/objections", {"fields": {"trigger_scene": "价格贵", "standard_reply": "先问预算", "next_step": "给套餐"}})
call("POST", "/api/v1/ammo/competitors", {"fields": {"competitor": "示例机构", "standard_reply": "对比售后"}})
call("POST", "/api/v1/ammo/scripts", {"fields": {"followup_scene": "comparing", "script_example": "您对比时最看重哪三项？", "delay_hours": 48}})
check("objection", len(call("GET", "/api/v1/ammo/objections")["objections"]) >= 1)
check("competitor", len(call("GET", "/api/v1/ammo/competitors")["competitors"]) >= 1)
check("script", len(call("GET", "/api/v1/ammo/scripts")["scripts"]) >= 2)

print("\n--- 案例投喂 ---")
case_text = "客户问1980贵不贵，我说包教会还有售后。客户犹豫说再考虑。第三天发学员案例，客户报名成交。"
call("POST", "/api/v1/ammo/cases/import", {"content": case_text, "title": "案例1"})
check("case-import", len(call("GET", "/api/v1/ammo/cases")["cases"]) >= 1)

print("\n--- 赢单引擎 ---")
call("POST", "/api/v1/winning/differentiators", {"fields": {"product": "普通人AI课程", "differentiator": "包教会", "customer_concern": "怕没效果"}})
call("POST", "/api/v1/winning/evidence", {"fields": {"evidence_type": "case", "title": "学员案例"}})
call("POST", "/api/v1/winning/tools", {"fields": {"tool_type": "trial", "name": "体验课"}})
check("differentiator", len(call("GET", "/api/v1/winning/differentiators")["items"]) >= 1)
check("evidence", len(call("GET", "/api/v1/winning/evidence")["items"]) >= 1)
check("tool", len(call("GET", "/api/v1/winning/tools")["items"]) >= 1)

print("\n--- 会话摘要与状态机 ---")
msg = "你们和别家比怎么样？我担心1980太贵"
call("POST", "/api/v1/chat", {"message": msg, "from_user": "solda-test", "nickname": "测试"})
summaries = call("GET", "/api/v1/conversations/summaries")["summaries"]
check("summary-created", len(summaries) >= 1)
check("status-comparing", summaries[0]["sales_status"] == "comparing")
check("concern-price", "价格" in (summaries[0]["core_concern"] or ""))
stats = call("GET", "/api/v1/conversations/stats")
check("conv-stats", stats["total"] >= 1 and stats["next_step_rate"] >= 0)

print("\n--- 预约优惠 ---")
call("POST", "/api/v1/appointments", {"fields": {"session_id": "solda-test", "title": "试听", "start_at": "2026-08-12 10:00:00", "owner": "叙白"}})
coupon = call("POST", "/api/v1/coupons", {"fields": {"name": "首单优惠", "coupon_type": "discount", "value": "200", "valid_days": 7}})["coupon"]
call("POST", f"/api/v1/coupons/{coupon['id']}/grant", {"fields": {"session_id": "solda-test"}})
check("appointment", len(call("GET", "/api/v1/appointments")["appointments"]) >= 1)
check("user-coupon", len(call("GET", "/api/v1/user-coupons")["user_coupons"]) >= 1)

print("\n--- 优化中心 ---")
exp = call("POST", "/api/v1/optimization/experiments", {"name": "开场A/B", "kind": "script", "control": "A", "variant": "B"})["experiment"]
call("POST", f"/api/v1/optimization/runs?experiment_id={exp['id']}", {"session_id": "solda-test", "variant": "control", "result": "replied"})
call("POST", "/api/v1/optimization/reviews", {"content": "本周复盘"})
check("experiment", len(call("GET", "/api/v1/optimization/experiments")["experiments"]) >= 1)
check("run", len(call("GET", "/api/v1/optimization/runs")["runs"]) >= 1)
check("review", len(call("GET", "/api/v1/optimization/reviews")["reviews"]) >= 1)

print("\n--- 合规 ---")
rules = call("GET", "/api/v1/compliance/rules")["rules"]
check("compliance-seed", len(rules) >= 3)
from core.compliance import compliance_manager
stop = compliance_manager.check("我不买了，别再联系")
check("compliance-stop", stop.get("action") == "stop")

print("\n" + "=" * 60)
print(f"Solda 模式升级自测全部通过: {len(checks)} 项")
print("=" * 60)
