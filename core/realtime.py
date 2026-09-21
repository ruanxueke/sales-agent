"""WebSocket 实时通知中枢：新通知实时推送到中台

鉴权与隔离
----------
连接必须携带凭据（握手时校验，见 api_server.ws_notifications），并把身份绑定到连接上：
- payload 带 `tenant_id` 时，只推给该租户的连接；
- payload 不带 `tenant_id` 时，推给全部已鉴权连接；
- `tenant_id is None` 的连接（超管）能收到所有租户的消息。

这样即便某条通知里带了租户信息，也不会像原来那样广播给所有连接。
"""
from __future__ import annotations
import asyncio
import json
import logging

logger = logging.getLogger(__name__)


class NotificationHub:
    def __init__(self):
        # ws -> {"tenant_id": int|None, "actor": str}
        self._connections: dict = {}
        self._lock = asyncio.Lock()

    async def connect(self, ws, tenant_id: int | None = None, actor: str = ""):
        async with self._lock:
            self._connections[ws] = {"tenant_id": tenant_id, "actor": actor}

    async def disconnect(self, ws):
        async with self._lock:
            self._connections.pop(ws, None)

    def connection_count(self) -> int:
        return len(self._connections)

    async def broadcast(self, payload: dict):
        if not self._connections:
            return
        msg = json.dumps(payload, ensure_ascii=False)
        target_tenant = payload.get("tenant_id")
        async with self._lock:
            for ws, meta in list(self._connections.items()):
                if target_tenant is not None:
                    owner = meta.get("tenant_id")
                    # owner 为 None 表示跨租户视角（超管），照常接收
                    if owner is not None and owner != target_tenant:
                        continue
                try:
                    await ws.send_text(msg)
                except Exception:
                    self._connections.pop(ws, None)

    def publish_sync(self, payload: dict):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.broadcast(payload))
        except Exception as e:
            logger.warning(f"实时通知发布失败: {e}")


hub = NotificationHub()
