from __future__ import annotations

import threading
import sqlite3
import os
import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import pytest

from wechat_bridge.central_client import CentralClient
from wechat_bridge.binding import resolve_instance
from wechat_bridge.config import BridgeConfig, TargetConfig
from wechat_bridge.durable_queue import DurableQueue
from wechat_bridge.reader_adapter import CaptureReader
from wechat_bridge.run import WechatBridge
from wechat_bridge.runtime_lock import AlreadyRunningError, RuntimeLock
from wechat_bridge.secure_store import load as load_secret, save as save_secret


def test_runtime_lock_blocks_second_instance(tmp_path):
    lock_path = tmp_path / "bridge.lock"
    first = RuntimeLock(lock_path)
    first.acquire()
    try:
        with pytest.raises(AlreadyRunningError):
            RuntimeLock(lock_path).acquire()
    finally:
        first.release()


def test_multi_account_isolation(tmp_path):
    binding = tmp_path / "binding.json"
    first_id, first_status = resolve_instance(
        "desktop-shared",
        "wxid_account_a",
        binding,
    )
    second_id, second_status = resolve_instance(
        "desktop-shared",
        "wxid_account_b",
        binding,
    )
    assert first_id == "desktop-shared"
    assert first_status == "new"
    assert second_id == "desktop-shared#wxid_account_b"
    assert second_status == "conflict"

    lock_a = RuntimeLock(tmp_path / "account-a.lock")
    lock_b = RuntimeLock(tmp_path / "account-b.lock")
    lock_a.acquire()
    lock_b.acquire()
    lock_a.release()
    lock_b.release()


def test_queue_stress_backlog(tmp_path):
    queue = DurableQueue(tmp_path / "queue.db")
    for index in range(1000):
        queue.put_event(
            {
                "message_id": f"message-{index}",
                "target_username": "wxid_customer",
                "content": "stress",
            }
        )
    for index in range(200):
        queue.put_task(
            {
                "task_id": f"task-{index}",
                "target_username": "wxid_customer",
                "content": "reply",
            }
        )
    metrics = queue.metrics()
    assert metrics["events"]["pending"] == 1000
    assert metrics["tasks"]["pending"] == 200
    assert len(queue.pending_events(limit=50)) == 50
    assert len(queue.recoverable_tasks(limit=50)) == 0


def test_customer_name_prefers_remark(tmp_path):
    contact_dir = tmp_path / "contact"
    contact_dir.mkdir()
    db = contact_dir / "contact.db"
    connection = sqlite3.connect(db)
    connection.execute(
        "create table contact (username text, nick_name text, remark text)"
    )
    connection.execute(
        "insert into contact values (?, ?, ?)",
        ("wxid_customer", "personal nickname", "customer remark"),
    )
    connection.commit()
    connection.close()

    reader = CaptureReader.__new__(CaptureReader)
    reader.store = SimpleNamespace(d=tmp_path)
    assert reader._nicknames()["wxid_customer"] == "customer remark"


def test_detect_wechat_login_returns_account_nickname(tmp_path):
    (tmp_path / "message.db").write_bytes(b"")
    reader = CaptureReader.__new__(CaptureReader)
    reader.config = SimpleNamespace(window_title="微信")
    reader.module = SimpleNamespace(wechat_running=lambda: [1001])
    reader.account = SimpleNamespace(name="wxid_self_account")
    reader.store = SimpleNamespace(
        d=tmp_path,
        self_username="wxid_self",
        contacts=lambda: {"wxid_self": "接待微信昵称"},
    )

    result = reader.detect_wechat_login()

    assert result["logged_in"] is True
    assert result["account_id"] == "wxid_self_account"
    assert result["account_name"] == "接待微信昵称"


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI only")
def test_dpapi_secret_roundtrip(tmp_path):
    path = tmp_path / "secret.bin"
    save_secret(path, "bridge-secret")
    assert load_secret(path) == "bridge-secret"


def test_http_retry_recovers_from_502():
    class Handler(BaseHTTPRequestHandler):
        calls = 0

        def do_GET(self):
            type(self).calls += 1
            if type(self).calls < 3:
                self.send_response(502)
                self.end_headers()
                self.wfile.write(b"bad gateway")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = BridgeConfig(
            central_base_url=f"http://127.0.0.1:{server.server_port}",
            request_retry_total=3,
            request_retry_backoff_seconds=0.1,
        )
        assert CentralClient(config).health() == {"status": "ok"}
        assert Handler.calls == 3
    finally:
        server.shutdown()


def test_durable_event_queue_survives_restart(tmp_path):
    path = tmp_path / "queue.db"
    first = DurableQueue(path)
    first.put_event(
        {
            "message_id": "message-1",
            "target_username": "wxid_customer",
            "content": "hello",
        }
    )
    second = DurableQueue(path)
    pending = second.pending_events()
    assert len(pending) == 1
    assert pending[0]["event"]["content"] == "hello"
    second.complete_event("message-1")
    assert second.pending_events() == []


def test_uncertain_send_is_not_replayed(tmp_path):
    class State:
        def task_status(self, task_id):
            return ""

    class Central:
        def __init__(self):
            self.acks = []

        def get_tasks(self, claim=True):
            return []

        def ack_task(self, task_id, status, error="", **kwargs):
            self.acks.append((task_id, status, error, kwargs))
            return {"ok": True}

    class Sender:
        def send(self, *args, **kwargs):
            raise AssertionError("uncertain task must not be sent again")

    bridge = WechatBridge.__new__(WechatBridge)
    bridge.config = BridgeConfig(
        account_id="account-1",
        auto_discover_contacts=True,
        default_contact_mode="auto",
    )
    bridge.dry_run = False
    bridge.queue = DurableQueue(tmp_path / "queue.db")
    task = {
        "task_id": "task-uncertain",
        "target_type": "contact",
        "target_name": "customer",
        "target_username": "wxid_customer",
        "content": "reply",
        "mode": "auto",
    }
    bridge.queue.put_task(task)
    bridge.queue.update_task(
        task["task_id"],
        status="awaiting_receipt",
        stage="entered",
    )
    bridge.state = State()
    bridge.central = Central()
    bridge.sender = Sender()
    bridge._verify_sent = lambda task, target: False

    result = bridge.process_tasks()
    assert result["failed"] == 1
    assert bridge.central.acks[0][1] == "manual_review"
    assert bridge.central.acks[0][3]["failure_code"] == "SEND_UNCONFIRMED"


def test_process_200_tasks_pressure(tmp_path):
    class State:
        def task_status(self, task_id):
            return ""

        def allow_send(self, target_key, daily_limit, hourly_limit):
            return True, ""

        def record_send(self, target_key):
            pass

        def mark_task(self, task_id, status):
            pass

    class Central:
        def __init__(self, tasks):
            self.tasks = tasks
            self.acks = []

        def get_tasks(self, claim=True):
            return self.tasks

        def ack_task(self, task_id, status, error="", **kwargs):
            self.acks.append((task_id, status))
            return {"ok": True}

    class Sender:
        def send(self, task, mode, on_stage=None):
            if on_stage:
                on_stage("target_verified")
                on_stage("before_enter")
                on_stage("entered")
            return SimpleNamespace(
                ok=True,
                status="sent",
                detail="sent",
                failure_code="",
                diagnostic_path="",
            )

    class Notifier:
        def notify(self, *args, **kwargs):
            pass

    tasks = [
        {
            "task_id": f"pressure-{index}",
            "target_type": "contact",
            "target_name": "customer",
            "target_username": "wxid_customer",
            "content": f"reply-{index}",
            "mode": "auto",
        }
        for index in range(200)
    ]
    bridge = WechatBridge.__new__(WechatBridge)
    bridge.config = BridgeConfig(
        account_id="account-1",
        auto_discover_contacts=True,
        default_contact_mode="auto",
        verify_send_with_reader=True,
    )
    bridge.dry_run = False
    bridge.queue = DurableQueue(tmp_path / "queue.db")
    bridge.state = State()
    bridge.central = Central(tasks)
    bridge.sender = Sender()
    bridge.notifier = Notifier()
    bridge._verify_sent = lambda task, target: True
    bridge.audit = type("Audit", (), {"log": lambda *args, **kwargs: None})()

    result = bridge.process_tasks()
    assert result["sent"] == 200
    assert len(bridge.central.acks) == 200


def test_release_versions_are_aligned():
    root = __import__("pathlib").Path(__file__).resolve().parent.parent
    package = json.loads(
        (root / "desktop-client" / "package.json").read_text(encoding="utf-8")
    )
    main_source = (root / "desktop-client" / "main.js").read_text(encoding="utf-8")
    run_source = (root / "wechat_bridge" / "run.py").read_text(encoding="utf-8")
    package_version = str(package["version"])
    assert package_version == "1.0.11"
    agent_versions = {
        re.search(r"BRIDGE_AGENT_VERSION\s*=\s*['\"]([^'\"]+)", main_source).group(1),
        re.search(r'BRIDGE_AGENT_VERSION\s*=\s*"([^"]+)"', run_source).group(1),
    }
    assert agent_versions == {"2026.09.15.1"}


def test_send_retry_recovers_from_ui_failure():
    class Sender:
        def __init__(self):
            self.calls = 0

        def send(self, task, mode, on_stage=None):
            self.calls += 1
            if self.calls < 3:
                return SimpleNamespace(ok=False, status="failed", detail="temporary")
            return SimpleNamespace(ok=True, status="sent", detail="sent")

    class Audit:
        def log(self, *args, **kwargs):
            pass

    bridge = WechatBridge.__new__(WechatBridge)
    bridge.config = BridgeConfig(
        send_retry_attempts=3,
        send_retry_backoff_seconds=0.01,
    )
    bridge.sender = Sender()
    bridge.audit = Audit()
    result = bridge._send_with_retry(
        {"task_id": "task-1"},
        TargetConfig(
            target_name="customer",
            target_username="wxid_customer",
            mode="auto",
        ),
    )
    assert result.ok
    assert bridge.sender.calls == 3


def test_new_message_after_start_is_not_baselined(tmp_path):
    class State:
        def __init__(self):
            self.seen = set()
            self.initialized = False

        def target_initialized(self, key):
            return self.initialized

        def mark_target_initialized(self, key):
            self.initialized = True

        def mark_message(self, key):
            self.seen.add(key)

        def seen_message(self, key):
            return key in self.seen

    class Reader:
        def read_messages(self, target, **kwargs):
            return [
                {"time": 900, "sender": "old", "text": "history"},
                {"time": 1101, "sender": "customer", "text": "hello"},
            ]

    class Central:
        def __init__(self):
            self.events = []

        def send_event(self, event):
            self.events.append(event)
            return {"ok": True, "task_id": "task-1"}

    class Audit:
        def log(self, *args, **kwargs):
            pass

    class Notifier:
        def notify(self, *args, **kwargs):
            pass

    bridge = WechatBridge.__new__(WechatBridge)
    bridge.config = BridgeConfig(
        account_id="account-1",
        auto_discover_contacts=False,
        targets=[
            TargetConfig(
                target_name="customer",
                target_username="wxid_customer",
                enabled=True,
                mode="auto",
            )
        ],
    )
    bridge.dry_run = False
    bridge.state = State()
    bridge.reader = Reader()
    bridge.central = Central()
    bridge.queue = DurableQueue(tmp_path / "queue.db")
    bridge.audit = Audit()
    bridge.notifier = Notifier()
    bridge._started_at = 1000

    assert bridge.process_messages()["sent"] == 1
    assert [event["content"] for event in bridge.central.events] == ["hello"]
    assert len(bridge.state.seen) == 2


def test_all_contact_names_sync_regardless_of_message_age():
    class Reader:
        def list_customer_sessions(self, since=None, limit=500):
            assert since is None
            return [
                {
                    "username": "wxid_customer",
                    "name": "customer remark",
                    "time": 1,
                }
            ]

    class Central:
        def __init__(self):
            self.contacts = []

        def sync_contact_names(self, contacts):
            self.contacts.extend(contacts)
            return {"ok": True, "updated": len(contacts)}

    class Audit:
        def log(self, *args, **kwargs):
            pass

    bridge = WechatBridge.__new__(WechatBridge)
    bridge.config = BridgeConfig(
        account_id="account-1",
        auto_discover_contacts=True,
        default_contact_mode="auto",
    )
    bridge.reader = Reader()
    bridge.central = Central()
    bridge.audit = Audit()
    bridge._synced_contact_names = {}

    bridge.sync_all_contact_names()
    assert bridge.central.contacts == [
        {
            "target_username": "wxid_customer",
            "target_name": "customer remark",
        }
    ]
