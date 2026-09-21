"""多租户隔离自测：凭据即租户 + 桥接任务不跨租户 + 转人工误判防护

对应审计清单 A2（多租户在个人微信链路上失效）与 P1-4 的验收。
运行：python tests/test_tenant_isolation.py
"""
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

cfg.settings.API_KEYS = "sk-tenant-a,sk-tenant-b,sk-super"
cfg.settings.ADMIN_API_KEYS = ""
cfg.settings.API_KEY_TENANTS = "sk-tenant-a=0,sk-tenant-b=1"
cfg.settings.SUPER_ADMIN_API_KEYS = "sk-super"
cfg.settings.DEFAULT_TENANT_ID = 0

from core.security import current_tenant, current_tenant_filter
from core.handover_words import contains_handover_keyword
from core.tenant_scope import filter_by_tenant

checks: list[str] = []


def check(name: str, cond: bool, detail: str = ""):
    assert cond, f"{name}: {detail}"
    checks.append(name)
    print(f"  {name} [OK]")


class FakeRequest:
    def __init__(self, key: str = "", path: str = "/api/v1/personal-wechat/status"):
        self.headers = {"X-API-Key": key} if key else {}
        self.url = type("U", (), {"path": path})()
        self.client = type("C", (), {"host": "127.0.0.1"})()


print("=" * 60)
print("多租户隔离自测")
print("=" * 60)

print("\n--- 凭据即租户 ---")
check("tenant-a = 0", current_tenant(FakeRequest("sk-tenant-a")) == 0)
check("tenant-b = 1", current_tenant(FakeRequest("sk-tenant-b")) == 1)
check(
    "API Key 不再返回 None（旧规则是 None=看全部）",
    current_tenant(FakeRequest("sk-tenant-b")) is not None,
)
check("未绑定 Key 落默认租户", current_tenant(FakeRequest("sk-unknown")) == cfg.settings.DEFAULT_TENANT_ID)
check("本地开发模式（无 Key 配置）也有确定租户", isinstance(current_tenant(FakeRequest("")), int))

print("\n--- 跨租户视角必须显式索取 ---")
check(
    "普通租户 Key 的过滤条件就是自身租户",
    current_tenant_filter(FakeRequest("sk-tenant-b")) == 1,
)
check(
    "未列入 SUPER_ADMIN 的 Key 拿不到跨租户视角",
    current_tenant_filter(FakeRequest("sk-tenant-a")) is not None,
)
check(
    "仅 SUPER_ADMIN_API_KEYS 才能拿到 None",
    current_tenant_filter(FakeRequest("sk-super")) is None,
)

print("\n--- filter_by_tenant 语义 ---")
no_tenant_rows = [{"id": 1, "name": "产品A"}, {"id": 2, "name": "产品B"}]
check(
    "无租户维度的表不被过滤（79 个模型里 65 个属于这类）",
    len(filter_by_tenant(no_tenant_rows, 0)) == 2 and len(filter_by_tenant(no_tenant_rows, 1)) == 2,
)
tenant_rows = [
    {"id": 1, "tenant_id": 0},
    {"id": 2, "tenant_id": 1},
    {"id": 3, "tenant_id": None},
]
check("租户 0 只看自己的", [r["id"] for r in filter_by_tenant(tenant_rows, 0)] == [1, 3])
check("租户 1 只看自己的", [r["id"] for r in filter_by_tenant(tenant_rows, 1)] == [2])
check("超级管理员看全部", len(filter_by_tenant(tenant_rows, None)) == 3)

print("\n--- 桥接任务不跨租户 ---")
from core.personal_wechat import personal_wechat_service
from core.db import init_db

init_db()

base_event = {
    "account_id": "wxid_demo",
    "target_type": "contact",
    "target_name": "客户",
    "target_username": "wxid_customer",
    "sender_name": "客户",
    "content": "你好，想了解一下课程",
    "created_at": 1757000000,
    "mode": "draft",
}
r0 = personal_wechat_service.ingest_event(dict(base_event, message_id="m-tenant0"), tenant_id=0)
r1 = personal_wechat_service.ingest_event(dict(base_event, message_id="m-tenant1"), tenant_id=1)
check("租户 0 事件入库", r0.get("ok") is True, str(r0))
check("租户 1 事件入库", r1.get("ok") is True, str(r1))

# 入库后任务是 generating（要等 LLM 生成），这里直接置为 pending 以便验证认领隔离
from sqlalchemy import select

from core.db import session_scope
from core.models import PersonalWechatReplyTask

with session_scope() as _s:
    _rows = _s.execute(select(PersonalWechatReplyTask)).scalars().all()
    for _row in _rows:
        _row.status = "pending"
    _tenants = {_row.tenant_id for _row in _rows}
check("两条任务确实分属租户 0 与 1", _tenants == {0, 1}, str(_tenants))

t0 = personal_wechat_service.claim_tasks(tenant_id=0, account_id="wxid_demo", limit=10, claimed_by="bridge-0")
t1 = personal_wechat_service.claim_tasks(tenant_id=1, account_id="wxid_demo", limit=10, claimed_by="bridge-1")
check("租户 0 只领到自己的 1 条", len(t0) == 1, f"拿到 {len(t0)} 条")
check("租户 1 只领到自己的 1 条", len(t1) == 1, f"拿到 {len(t1)} 条")
check("认领结果租户号正确", t0[0]["tenant_id"] == 0 and t1[0]["tenant_id"] == 1)
check("两条任务确实属于不同租户", t0[0]["task_id"] != t1[0]["task_id"])

print("\n--- 实例号跨租户占用被拒绝 ---")
hb = {"instance_id": "desktop-shared", "status": "online"}
a = personal_wechat_service.heartbeat(dict(hb), tenant_id=0)
b = personal_wechat_service.heartbeat(dict(hb), tenant_id=1)
check("租户 0 心跳成功", a.get("ok") is True, str(a))
check("租户 1 用同一实例号被拒绝", b.get("ok") is False and "占用" in str(b.get("error", "")), str(b))

print("\n--- 转人工关键词误判防护 ---")
check("『你们教人工智能吗』不应转人工", contains_handover_keyword("你们教人工智能吗", "wechat") is False)
check("『我要转人工』应转人工", contains_handover_keyword("我要转人工", "wechat") is True)
check("『人工客服』应转人工", contains_handover_keyword("找一下人工客服", "wechat") is True)

print("\n" + "=" * 60)
print(f"多租户隔离自测通过：{len(checks)} 项")
print("=" * 60)
