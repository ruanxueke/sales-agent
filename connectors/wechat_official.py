"""
微信公众号连接器 - FastAPI Web 服务
接收微信服务器推送的消息并调用统一路由处理
"""
from __future__ import annotations
import json
import logging
import threading
import time
from typing import Callable, Optional

import requests
from fastapi import BackgroundTasks, FastAPI, Request, Response
from wechatpy import parse_message
from wechatpy.crypto import WeChatCrypto
from wechatpy.exceptions import InvalidSignatureException
from wechatpy.replies import TextReply

from config.settings import settings
from core.security import default_tenant_id
from core.tenancy import tenant_session_key

logger = logging.getLogger(__name__)


class OfficialAccountClient:
    """微信公众号 API 客户端：access_token 缓存 + 客服消息推送"""

    def __init__(self):
        self._token = None
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def get_access_token(self, force: bool = False) -> str:
        with self._lock:
            if not force and self._token and time.time() < self._expires_at - 300:
                return self._token
            url = "https://api.weixin.qq.com/cgi-bin/token"
            params = {
                "grant_type": "client_credential",
                "appid": settings.WECHAT_OFFICIAL_APP_ID,
                "secret": settings.WECHAT_OFFICIAL_APP_SECRET,
            }
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()
            token = data.get("access_token")
            if not token:
                raise RuntimeError(f"获取 access_token 失败: {data}")
            self._token = token
            self._expires_at = time.time() + int(data.get("expires_in", 7200))
            return self._token

    def send_text(self, openid: str, content: str) -> None:
        url = "https://api.weixin.qq.com/cgi-bin/message/custom/send"
        body = {"touser": openid, "msgtype": "text", "text": {"content": content}}
        data = self._post(url, body)
        if data.get("errcode", 0) != 0:
            # access_token 可能过期，强制刷新后重试一次
            if data.get("errcode") == 40001:
                data = self._post(url, body, force_token=True)
            if data.get("errcode", 0) != 0:
                raise RuntimeError(f"客服消息发送失败: {data}")

    def get_menu(self) -> dict:
        return self._request("GET", "/cgi-bin/menu/get")

    def create_menu(self, menu: dict) -> dict:
        return self._request("POST", "/cgi-bin/menu/create", body=menu)

    def delete_menu(self) -> dict:
        return self._request("GET", "/cgi-bin/menu/delete")

    def _post(self, url: str, body: dict, force_token: bool = False) -> dict:
        token = self.get_access_token(force=force_token)
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        resp = requests.post(
            url,
            params={"access_token": token},
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=10,
        )
        return resp.json()

    def _request(self, method: str, path: str, body: dict = None, force_token: bool = False) -> dict:
        token = self.get_access_token(force=force_token)
        url = f"https://api.weixin.qq.com{path}"
        kwargs = {"params": {"access_token": token}, "timeout": 10}
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            kwargs["data"] = payload
            kwargs["headers"] = {"Content-Type": "application/json; charset=utf-8"}
        resp = requests.request(method, url, **kwargs)
        data = resp.json()
        if data.get("errcode") == 40001 and not force_token:
            return self._request(method, path, body=body, force_token=True)
        return data


official_client = OfficialAccountClient()


def _async_reply(
    msg_handler: Callable,
    user_id: str,
    content: str,
    session_id: str = "",
):
    """后台执行：生成回复并用客服消息接口推送给用户"""
    start = time.time()
    try:
        reply_text = msg_handler(content, session_id or user_id)
        elapsed = time.time() - start
        min_delay = getattr(settings, "MIN_REPLY_DELAY_SECONDS", 5.0)
        if elapsed < min_delay:
            time.sleep(min_delay - elapsed)
        from core.message_splitter import split_text
        max_len = getattr(settings, "REPLY_MAX_LENGTH", 20)
        parts = split_text(reply_text, max_len)
        split_delay = getattr(settings, "REPLY_SPLIT_DELAY_SECONDS", 1.5)
        for idx, part in enumerate(parts):
            official_client.send_text(user_id, part)
            if idx < len(parts) - 1:
                time.sleep(split_delay)
        logger.info(f"公众号异步回复成功 from={user_id} 共{len(parts)}条")
    except Exception as e:
        logger.error(f"公众号异步回复失败 from={user_id}: {e}")


def create_app(msg_handler: Optional[Callable] = None) -> FastAPI:
    """创建 FastAPI 应用

    Args:
        msg_handler: 统一消息处理函数，签名 (msg: str, from_user: str) -> str

    Returns:
        FastAPI 应用实例
    """
    if msg_handler is None:
        msg_handler = lambda msg, user: f"收到 {user} 的消息: {msg}（知识库待配置）"

    app = FastAPI(title="销售客服智能体 - 公众号")

    @app.get("/wechat")
    async def verify(
        signature: str,
        timestamp: str,
        nonce: str,
        echostr: str,
    ):
        """微信服务器地址验证（GET 请求）
        公众平台提交服务器配置时，微信会发 GET 请求验证
        """
        try:
            from wechatpy.utils import check_signature
            check_signature(
                settings.WECHAT_OFFICIAL_TOKEN or "",
                signature,
                timestamp,
                nonce,
            )
            echo_str = echostr
            logger.info("公众号验证成功")
            return Response(content=echo_str, media_type="text/plain")
        except InvalidSignatureException:
            logger.warning("公众号验证失败：签名不匹配")
            return Response(content="invalid signature", media_type="text/plain")
        except Exception as e:
            logger.error(f"公众号验证处理异常: {e}")
            return Response(content="invalid signature", media_type="text/plain")

    @app.post("/wechat")
    async def handle_message(request: Request, background_tasks: BackgroundTasks):
        """接收微信服务器推送的用户消息（POST 请求）"""
        body = (await request.body()).decode("utf-8", errors="replace")

        # 解密（安全/兼容模式：消息体包含 Encrypt 节点；明文模式直接解析）
        if settings.WECHAT_OFFICIAL_ENCODING_AES_KEY and "<Encrypt" in body:
            try:
                query = request.query_params
                signature = query.get("msg_signature") or query.get("signature") or ""
                timestamp = query.get("timestamp") or ""
                nonce = query.get("nonce") or ""
                crypto = WeChatCrypto(
                    token=settings.WECHAT_OFFICIAL_TOKEN or "",
                    encoding_aes_key=settings.WECHAT_OFFICIAL_ENCODING_AES_KEY or "",
                    app_id=settings.WECHAT_OFFICIAL_APP_ID or "",
                )
                msg_xml = crypto.decrypt_message(body, signature, timestamp, nonce)
            except Exception as e:
                logger.error(f"消息解密失败: {e}")
                return Response(content="decrypt error", media_type="text/plain")
        else:
            msg_xml = body

        # 解析消息
        try:
            msg = parse_message(msg_xml)
        except Exception as e:
            logger.error(f"消息解析失败: {e}")
            return Response(content="parse error", media_type="text/plain")

        user_id = msg.source  # 用户的 OpenID
        msg_id = str(getattr(msg, "id", "") or "")
        if msg_id:
            from core.idempotency import idempotency_store
            if not idempotency_store.mark(msg_id, source="official"):
                logger.info("忽略重复公众号消息 msg_id=%s", msg_id)
                return Response()

        tenant_id = default_tenant_id()
        session_id = tenant_session_key("official", tenant_id, user_id)

        # 关注/扫码事件：沉淀线索并记录带参二维码来源
        if msg.type == "event":
            event = getattr(msg, "event", "") or ""
            if event in ("subscribe", "SCAN"):
                try:
                    from core.lead import lead_manager
                    key = getattr(msg, "key", "") or ""
                    channel_id = key[8:] if key.startswith("qrscene_") else key
                    lead_manager.upsert_from_channel(
                        session_id=session_id,
                        source="official",
                        channel_id=channel_id,
                        tenant_id=tenant_id,
                    )
                    try:
                        from core.compliance_flow import compliance_flow
                        compliance_flow.add_consent(
                            session_id,
                            source="official",
                            content="关注公众号授权",
                            tenant_id=tenant_id,
                        )
                    except Exception as e:
                        logger.debug("create_app.handle_message 异常已忽略: %s", e)
                    logger.info(
                        "公众号%s事件 from=%s channel_id=%s",
                        event,
                        user_id,
                        channel_id or "无",
                    )
                except Exception as e:
                    logger.error(f"公众号线索沉淀失败: {e}")
                welcome = getattr(
                    settings,
                    "WECHAT_OFFICIAL_WELCOME",
                    "您好，欢迎关注！",
                )
                xml = TextReply(content=welcome, message=msg).render()
                return Response(content=xml, media_type="application/xml")
            logger.info(f"忽略其他事件: {event}")
            return Response()

        # 只处理文本消息
        if msg.type != "text":
            logger.info(f"忽略非文本消息: type={msg.type}")
            xml = TextReply(
                content="抱歉，我目前只能处理文字消息哦~",
                message=msg,
            ).render()
            return Response(content=xml, media_type="application/xml")

        content = msg.content.strip()
        logger.info(f"收到公众号消息 from={user_id}: {content}")

        # 异步模式：先响应微信，再用客服消息接口推送，避免微信 5 秒超时
        if settings.WECHAT_OFFICIAL_REPLY_MODE == "async" and settings.WECHAT_OFFICIAL_APP_SECRET:
            background_tasks.add_task(
                _async_reply,
                msg_handler,
                user_id,
                content,
                session_id,
            )
            return Response()

        # 被动模式：5 秒内同步返回回复
        try:
            reply_text = msg_handler(content, session_id)
        except Exception as e:
            logger.error(f"消息处理异常: {e}")
            reply_text = "抱歉，我暂时无法处理您的问题，请稍后再试。"

        reply = TextReply(content=reply_text, message=msg)
        return Response(content=reply.render(), media_type="application/xml")

    @app.get("/health")
    async def health():
        """健康检查接口"""
        return {"status": "ok", "service": "sales-agent-official"}

    return app


def run_server(app: FastAPI):
    """启动 Web 服务（阻塞）"""
    import uvicorn
    host = settings.WECHAT_OFFICIAL_SERVER_HOST
    port = settings.WECHAT_OFFICIAL_SERVER_PORT
    logger.info(f"公众号 Web 服务启动: http://{host}:{port}")
    logger.info(f"  验证地址: GET http://{host}:{port}/wechat")
    logger.info(f"  消息地址: POST http://{host}:{port}/wechat")
    logger.info(f"  健康检查: GET http://{host}:{port}/health")
    uvicorn.run(app, host=host, port=port, log_level="info")
