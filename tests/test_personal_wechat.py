"""个人微信中台接口与本地桥接测试。"""
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
from core.agent import sales_agent
from core.personal_wechat import personal_wechat_service
from wechat_bridge.audit import LocalState
from wechat_bridge.config import BridgeConfig, TargetConfig
from wechat_bridge.message_filter import normalize_message

client = TestClient(app)
checks = []


def check(name: str, condition: bool, detail: str = "") -> None:
    assert condition, f"{name}: {detail}"
    checks.append(name)
    print(f"  {name} [OK]")


print("=" * 60)
print("个人微信桥接测试")
print("=" * 60)

print("\n--- 中台事件与回复任务 ---")
sales_agent.chat = lambda message, session_id="", nickname=None, source="": "你好，请问想了解哪方面？"
event = {
    "account_id": "wxid_test_account",
    "target_type": "contact",
    "target_name": "测试客户",
    "target_username": "wxid_test_customer",
    "sender_name": "测试客户",
    "message_id": "msg-test-001",
    "content": "你好",
    "created_at": 1786500000,
    "is_self": False,
    "mode": "draft",
}
r = client.post("/api/v1/personal-wechat/events", json=event)
body = r.json()
check("event-ingest", r.status_code == 200 and body["ok"] and body["task_id"], str(body))

r = client.get(
    "/api/v1/personal-wechat/tasks",
    params={
        "account_id": "wxid_test_account",
        "claim": "false",
    },
)
tasks = r.json()["items"]
check(
    "reply-generated",
    len(tasks) == 1 and tasks[0]["content"] == "你好，请问想了解哪方面？",
    str(tasks),
)
task_id = tasks[0]["task_id"]

r = client.get(
    "/api/v1/personal-wechat/tasks",
    params={
        "account_id": "wxid_test_account",
        "instance_id": "test-bridge",
    },
)
claimed = r.json()["items"]
check("task-claim", len(claimed) == 1 and claimed[0]["status"] == "claimed")

r = client.post(
    f"/api/v1/personal-wechat/tasks/{task_id}/ack",
    json={"status": "drafted", "error": ""},
)
check("task-ack", r.status_code == 200 and r.json()["task"]["status"] == "drafted")

r = client.post(
    "/api/v1/personal-wechat/bridge/heartbeat",
    json={
        "instance_id": "test-bridge",
        "account_id": "wxid_test_account",
        "status": "online",
        "mode": "draft",
        "poll_interval_seconds": 3,
        "detail": {"target_count": 1},
    },
)
check("bridge-heartbeat", r.status_code == 200 and r.json()["ok"])
r = client.post(
    "/api/v1/personal-wechat/settings",
    json={
        "instance_id": "test-bridge",
        "recognition_enabled": True,
        "detect_wechat_login": False,
    },
)
check(
    "bridge-settings-update",
    r.status_code == 200
    and r.json()["instance"]["detect_wechat_login"] is False
    and r.json()["instance"]["recognition_enabled"] is True,
)
r = client.get(
    "/api/v1/personal-wechat/settings",
    params={"instance_id": "test-bridge"},
)
check(
    "bridge-settings-read",
    r.status_code == 200
    and r.json()["settings"]["detect_wechat_login"] is False
    and r.json()["settings"]["recognition_enabled"] is True,
)
r = client.get("/api/v1/personal-wechat/status")
status_body = r.json()
check(
    "bridge-status",
    r.status_code == 200
    and status_body["online"]
    and status_body["task_counts"].get("drafted") == 1,
    str(status_body),
)
r = client.get("/ready")
check(
    "service-ready",
    r.status_code == 200
    and r.json()["status"] == "ready"
    and r.json()["database"] is True,
    str(r.json()),
)

r = client.post("/api/v1/personal-wechat/events", json=event)
check(
    "event-dedupe",
    r.status_code == 200 and r.json().get("deduped") is True,
    str(r.json()),
)

print("\n--- 客户备注名统一同步 ---")
from sqlalchemy import select

from core.db import session_scope
from core.models import ChannelSession, Customer, Lead, PersonalWechatReplyTask

old_name = "old-customer-name"
remark_name = "remark-customer-name"
stable_session_key = "personal_wechat:0:wxid_test_account:wxid_test_customer"
with session_scope() as session:
    channel_session = session.execute(
        select(ChannelSession).where(
            ChannelSession.channel == "personal_wechat",
            ChannelSession.external_id == "wxid_test_customer",
        )
    ).scalars().first()
    channel_session.nickname = old_name
    lead = Lead(
        tenant_id=0,
        session_id=stable_session_key,
        nickname=old_name,
        display_id=old_name,
        source="personal_wechat",
        status="assigned",
        owner="tester",
    )
    customer = Customer(
        session_id=stable_session_key,
        nickname=old_name,
        display_id=old_name,
        source="personal_wechat",
    )
    session.add_all([lead, customer])
    session.flush()
    reply_task = session.execute(
        select(PersonalWechatReplyTask).where(
            PersonalWechatReplyTask.target_username == "wxid_test_customer"
        )
    ).scalars().first()
    reply_task.target_name = old_name

r = client.post(
    "/api/v1/personal-wechat/contacts/sync",
    json={
        "account_id": "wxid_test_account",
        "contacts": [
            {
                "target_username": "wxid_test_customer",
                "target_name": remark_name,
            }
        ],
    },
)
with session_scope(read_only=True) as session:
    synced_session = session.execute(
        select(ChannelSession).where(
            ChannelSession.external_id == "wxid_test_customer"
        )
    ).scalars().first()
    synced_lead = session.execute(
        select(Lead).where(Lead.session_id == stable_session_key)
    ).scalars().first()
    synced_customer = session.execute(
        select(Customer).where(Customer.session_id == stable_session_key)
    ).scalars().first()
    synced_task = session.execute(
        select(PersonalWechatReplyTask).where(
            PersonalWechatReplyTask.target_username == "wxid_test_customer"
        )
    ).scalars().first()
check(
    "contact-name-sync",
    r.status_code == 200
    and synced_session.nickname == remark_name
    and synced_lead.nickname == remark_name
    and synced_lead.display_id == remark_name
    and synced_customer.nickname == remark_name
    and synced_customer.display_id == remark_name
    and synced_task.target_name == remark_name,
    str(r.json()),
)

r = client.post(
    f"/api/v1/personal-wechat/tasks/{task_id}/ack",
    json={
        "status": "failed",
        "error": "temporary UI failure",
        "failure_code": "RETRYABLE_UI",
        "failure_stage": "send",
    },
)
check(
    "task-retry-scheduled",
    r.status_code == 200
    and r.json()["task"]["status"] == "pending"
    and r.json()["task"]["failure_code"] == "RETRYABLE_UI"
    and r.json()["task"]["next_retry_at"],
    str(r.json()),
)
r = client.post(f"/api/v1/personal-wechat/tasks/{task_id}/retry")
check(
    "task-manual-retry",
    r.status_code == 200
    and r.json()["task"]["status"] == "pending"
    and r.json()["task"]["next_retry_at"] == "",
    str(r.json()),
)
r = client.get(
    "/api/v1/personal-wechat/metrics",
    params={"account_id": "wxid_test_account"},
)
check(
    "bridge-metrics",
    r.status_code == 200
    and r.json()["total"] >= 1
    and "status_counts" in r.json(),
    str(r.json()),
)
try:
    personal_wechat_service._validate_reply("api key: sk-test")
    sensitive_blocked = False
except RuntimeError:
    sensitive_blocked = True
check(
    "reply-sensitive-guard",
    sensitive_blocked
    and personal_wechat_service._validate_reply("这是正常回复") == "这是正常回复",
)

print("\n--- 白名单消息标准化 ---")
config = BridgeConfig(
    account_id="wxid_test_account",
    self_names=["机器人账号"],
    targets=[],
)
dedicated = BridgeConfig.load(
    ROOT / "wechat_bridge" / "config.dedicated-account.example.json"
)
check(
    "dedicated-account-config",
    dedicated.auto_discover_contacts
    and dedicated.default_contact_mode == "auto"
    and not dedicated.targets,
)
target = TargetConfig(
    target_type="contact",
    target_name="测试客户",
    target_username="wxid_test_customer",
    enabled=True,
    mode="draft",
)
normalized = normalize_message(
    {
        "time": 1786500001,
        "sender": "测试客户",
        "type": "文本",
        "text": "请问价格",
    },
    config,
    target,
)
check(
    "message-normalize",
    normalized is not None
    and normalized["target_username"] == "wxid_test_customer"
    and normalized["mode"] == "draft",
)
renamed = normalize_message(
    {
        "time": 1786500002,
        "sender": "测试客户新昵称",
        "text": "改了名称后还能识别吗",
        "target_name": "测试客户新昵称",
        "target_username": "wxid_test_customer",
    },
    config,
    target,
)
check(
    "detected-name-used",
    renamed is not None and renamed["target_name"] == "测试客户新昵称",
)
check(
    "self-message-filter",
    normalize_message(
        {"time": 1786500003, "sender": "机器人账号", "text": "自己发的"},
        config,
        target,
    )
    is None,
)
check(
    "media-filter",
    normalize_message(
        {"time": 1786500003, "sender": "测试客户", "text": "[图片]"},
        config,
        target,
    )
    is None,
)

print("\n--- 本地去重状态 ---")
state_file = Path(tempfile.mkdtemp()) / "state.json"
state = LocalState(state_file)
state.mark_message("fingerprint-1")
check("local-dedupe", state.seen_message("fingerprint-1"))
state.mark_task("task-1", "drafted")
check("local-task-state", state.task_status("task-1") == "drafted")
check(
    "target-baseline",
    not state.target_initialized("target-1"),
)
state.mark_target_initialized("target-1")
check("target-baseline-mark", state.target_initialized("target-1"))
allowed, _ = state.allow_send("target-1", daily_limit=1, hourly_limit=1)
check("send-limit-before", allowed)
state.record_send("target-1")
blocked, _ = state.allow_send("target-1", daily_limit=1, hourly_limit=1)
check("send-limit-after", not blocked)

from core.db import engine

engine.dispose()
try:
    os.unlink(_tmp_db.name)
except OSError:
    pass

print("\n" + "=" * 60)
print(f"个人微信桥接测试全部通过: {len(checks)} 项")
print("=" * 60)
