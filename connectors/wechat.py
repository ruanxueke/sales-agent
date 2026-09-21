"""微信连接器 - 个人微信"""
from __future__ import annotations
import logging
from typing import Callable, Optional
from config.settings import settings

logger = logging.getLogger(__name__)


class WeChatConnector:
    """微信连接器（个人微信）"""

    def __init__(self, msg_handler: Optional[Callable] = None):
        self.msg_handler = msg_handler or self._default_handler
        self._client = None
        self._running = False

    def _default_handler(self, msg: str, from_user: str) -> str:
        return f"收到 {from_user} 的消息: {msg}（知识库待配置，暂无自动回复）"

    def login(self):
        """登录个人微信"""
        self._login_personal()

    def _login_personal(self):
        try:
            import itchat
            import itchat.content as ct

            # 注册文本消息处理
            @itchat.msg_register(ct.TEXT)
            def text_reply(msg):
                from core.idempotency import idempotency_store
                msg_id = str(msg.get("MsgId") or "")
                if msg_id and not idempotency_store.mark(msg_id, source="wechat"):
                    logger.info("忽略重复个人微信消息 msg_id=%s", msg_id)
                    return None
                user = msg["User"].get("NickName", msg["User"]["UserName"])
                logger.info(f"收到来自 {user} 的消息: {msg['Text']}")
                reply = self.msg_handler(msg["Text"], user)
                if reply:
                    return reply

            # 注册图片消息处理
            @itchat.msg_register(ct.PICTURE)
            def pic_reply(msg):
                from core.idempotency import idempotency_store
                msg_id = str(msg.get("MsgId") or "")
                if msg_id and not idempotency_store.mark(msg_id, source="wechat"):
                    logger.info("忽略重复个人微信图片消息 msg_id=%s", msg_id)
                    return None
                user = msg["User"].get("NickName", msg["User"]["UserName"])
                logger.info(f"收到来自 {user} 的图片")
                reply = self.msg_handler("[图片消息]", user)
                if reply:
                    return reply

            self._client = itchat
            itchat.auto_login(
                hotReload=settings.WECHAT_PERSONAL_HOT_RELOAD,
                picDir=settings.WECHAT_PERSONAL_QR_PATH,
            )
            logger.info("个人微信登录成功")

        except ImportError:
            logger.error("请先安装 itchat-uos: pip install itchat-uos")
        except Exception as e:
            logger.error(f"微信登录失败: {e}")
            raise

    def send_message(self, to_user: str, message: str):
        if self._client:
            users = self._client.search_friends(name=to_user)
            if users:
                self._client.send(message, users[0]["UserName"])

    def start(self):
        self._running = True
        logger.info("微信监听已启动，等待消息...")
        if self._client:
            self._client.run()

    def stop(self):
        self._running = False
        logger.info("微信监听已停止")
