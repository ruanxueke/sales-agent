"""销售智能体中台 HTTP 客户端。"""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from wechat_bridge.config import BridgeConfig


class CentralClient:
    def __init__(self, config: BridgeConfig):
        self.config = config
        self.session = requests.Session()
        self.headers = {"Accept": "application/json"}
        if config.api_key:
            self.headers["X-API-Key"] = config.api_key
        retry = Retry(
            total=max(0, config.request_retry_total),
            connect=max(0, config.request_retry_total),
            read=max(0, config.request_retry_total),
            status=max(0, config.request_retry_total),
            backoff_factor=max(0.1, config.request_retry_backoff_seconds),
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=4,
            pool_maxsize=8,
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.timeout = (
            max(1.0, config.request_connect_timeout_seconds),
            max(1.0, config.request_timeout_seconds),
        )

    def _url(self, path: str) -> str:
        return f"{self.config.central_base_url.rstrip('/')}{path}"

    def _request(self, method: str, path: str, **kwargs):
        response = self.session.request(
            method,
            self._url(path),
            headers=self.headers,
            timeout=self.timeout,
            **kwargs,
        )
        response.raise_for_status()
        return response.json()

    def health(self) -> dict:
        return self._request("GET", "/health")

    def send_event(self, event: dict) -> dict:
        return self._request("POST", "/api/v1/personal-wechat/events", json=event)

    def sync_contact_names(self, contacts: list[dict]) -> dict:
        if not contacts:
            return {"ok": True, "updated": 0}
        return self._request(
            "POST",
            "/api/v1/personal-wechat/contacts/sync",
            json={
                "account_id": self.config.account_id,
                "contacts": contacts,
            },
        )

    def get_tasks(self, claim: bool = True, limit: int = 20) -> list[dict]:
        result = self._request(
            "GET",
            "/api/v1/personal-wechat/tasks",
            params={
                "account_id": self.config.account_id,
                "instance_id": self.config.instance_id,
                "limit": limit,
                "claim": str(claim).lower(),
            },
        )
        return list(result.get("items") or [])

    def ack_task(
        self,
        task_id: str,
        status: str,
        error: str = "",
        failure_code: str = "",
        failure_stage: str = "",
        diagnostic_path: str = "",
    ) -> dict:
        return self._request(
            "POST",
            f"/api/v1/personal-wechat/tasks/{task_id}/ack",
            json={
                "status": status,
                "error": error,
                "failure_code": failure_code,
                "failure_stage": failure_stage,
                "diagnostic_path": diagnostic_path,
            },
        )

    def heartbeat(self, payload: dict) -> dict:
        return self._request(
            "POST",
            "/api/v1/personal-wechat/bridge/heartbeat",
            json=payload,
        )

    def status(self, instance_id: str = "") -> dict:
        return self._request(
            "GET",
            "/api/v1/personal-wechat/status",
            params={"instance_id": instance_id or self.config.instance_id},
        )

    def get_settings(self) -> dict:
        return self._request(
            "GET",
            "/api/v1/personal-wechat/settings",
            params={"instance_id": self.config.instance_id},
        )
