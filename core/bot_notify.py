"""机器人通知统一投递：容器内通过 host.docker.internal 访问宿主机机器人通知服务"""
from __future__ import annotations
import logging

import requests

from config.settings import settings

logger = logging.getLogger(__name__)


def send_bot_notify(target: str, content: str) -> bool:
    hosts = [getattr(settings, "BOT_HOST", "") or "host.docker.internal", "127.0.0.1"]
    for host in hosts:
        try:
            resp = requests.post(
                f"http://{host}:{settings.BOT_NOTIFY_PORT}/notify",
                json={"target_name": target, "content": content},
                timeout=6,
            )
            if resp.ok:
                return True
        except Exception as e:
            logger.warning("通知投递失败 %s: %s", host, e)
    return False
