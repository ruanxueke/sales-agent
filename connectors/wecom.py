"""企业微信客户联系通道：接收客户消息 → 销售 Agent 回复 → 以员工身份回发"""
from __future__ import annotations
import hashlib
import hmac
import logging
import time
import xml.etree.ElementTree as ET
from collections import deque

import requests
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from config.settings import settings
from core.security import default_tenant_id, require_admin, require_api_key
from core.tenancy import tenant_session_key

logger = logging.getLogger(__name__)

router = APIRouter()
admin_router = APIRouter(prefix="/api/v1", tags=["wecom"], dependencies=[Depends(require_api_key)])


def _mask(value: str) -> str:
    value = value or ""
    if len(value) <= 4:
        return "****"
    return value[:2] + "****" + value[-2:]


class WeComClient:
    def __init__(self):
        self._token = None
        self._expires_at = 0.0
        self._kf_token = None
        self._kf_expires_at = 0.0

    def get_access_token(self) -> str:
        if self._token and time.time() < self._expires_at - 300:
            return self._token
        url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
        data = requests.get(
            url,
            params={"corpid": settings.WECOM_CORP_ID, "corpsecret": settings.WECOM_CONTACT_SECRET},
            timeout=10,
        ).json()
        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"企业微信 access_token 获取失败: {data}")
        self._token = token
        self._expires_at = time.time() + int(data.get("expires_in", 7200))
        return token

    def send_text(self, touser: str, content: str) -> None:
        url = "https://qyapi.weixin.qq.com/cgi-bin/message/send"
        body = {
            "touser": touser,
            "msgtype": "text",
            "agentid": int(settings.WECOM_AGENT_ID or 0),
            "text": {"content": content},
        }
        data = requests.post(
            url,
            params={"access_token": self.get_access_token()},
            json=body,
            timeout=10,
        ).json()
        if data.get("errcode", 0) != 0:
            raise RuntimeError(f"企业微信消息发送失败: {data}")

    def get_kf_token(self) -> str:
        if self._kf_token and time.time() < self._kf_expires_at - 300:
            return self._kf_token
        url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
        data = requests.get(
            url,
            params={"corpid": settings.WECOM_CORP_ID, "corpsecret": settings.WECOM_KF_SECRET},
            timeout=10,
        ).json()
        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"微信客服 access_token 获取失败: {data}")
        self._kf_token = token
        self._kf_expires_at = time.time() + int(data.get("expires_in", 7200))
        return token

    def send_kf(self, external_userid: str, content: str) -> None:
        url = "https://qyapi.weixin.qq.com/cgi-bin/kf/send_msg"
        body = {
            "touser": external_userid,
            "open_kfid": settings.WECOM_KF_OPEN_KFID,
            "msgtype": "text",
            "text": {"content": content},
        }
        data = requests.post(
            url,
            params={"access_token": self.get_kf_token()},
            json=body,
            timeout=10,
        ).json()
        if data.get("errcode", 0) != 0:
            raise RuntimeError(f"微信客服消息发送失败: {data}")

    def transfer_kf_session(self, external_userid: str, open_kfid: str = "", service_state: int = 2, servicer: str = "") -> None:
        """微信客服转人工：service_state=2 进入待接入池；指定 servicer 时直接分配给接待人员。"""
        url = "https://qyapi.weixin.qq.com/cgi-bin/kf/service_state/trans"
        body = {
            "open_kfid": open_kfid or settings.WECOM_KF_OPEN_KFID,
            "external_userid": external_userid,
            "service_state": int(service_state or 2),
        }
        if servicer:
            body["servicer"] = servicer
        data = requests.post(
            url,
            params={"access_token": self.get_kf_token()}, json=body, timeout=10,
        ).json()
        if data.get("errcode", 0) != 0:
            raise RuntimeError(f"微信客服转人工失败: {data}")

    def sync_kf_messages(self, token: str, open_kfid: str = "") -> list[dict]:
        url = "https://qyapi.weixin.qq.com/cgi-bin/kf/sync_msg"
        cursor = ""
        messages = []
        for _ in range(10):
            body = {"cursor": cursor, "token": token, "limit": 1000, "voice_format": 1, "open_kfid": open_kfid}
            data = requests.post(url, params={"access_token": self.get_kf_token()}, json=body, timeout=10).json()
            if data.get("errcode", 0) != 0:
                raise RuntimeError(f"微信客服消息同步失败: {data}")
            messages.extend(data.get("msg_list") or [])
            cursor = data.get("next_cursor") or ""
            if not cursor:
                break
        return messages

    def status(self) -> dict:
        configured = bool(settings.WECOM_CORP_ID and settings.WECOM_CONTACT_SECRET and settings.WECOM_AGENT_ID)
        kf_configured = bool(settings.WECOM_CORP_ID and settings.WECOM_KF_SECRET and settings.WECOM_KF_OPEN_KFID)
        token_ok = False
        token_error = ""
        if configured:
            try:
                self.get_access_token()
                token_ok = True
            except Exception as e:
                token_error = str(e)[:200]
        return {
            "configured": configured,
            "token_ok": token_ok,
            "token_error": token_error,
            "corp_id": _mask(settings.WECOM_CORP_ID),
            "contact_secret_set": bool(settings.WECOM_CONTACT_SECRET),
            "agent_id": settings.WECOM_AGENT_ID or "",
            "kf_configured": kf_configured,
            "kf_open_kfid": settings.WECOM_KF_OPEN_KFID or "",
            "callback_url": f"{getattr(settings, 'PUBLIC_BASE_URL', 'http://127.0.0.1:5000').rstrip('/')}/wecom",
        }


wecom_client = WeComClient()

_kf_msg_ids: set[str] = set()
_kf_msg_id_order: deque[str] = deque()
MAX_KF_DEDUP = 2000


def _kf_remember(msgid: str) -> None:
    """内存兜底去重集合带上限，避免长时间运行无限膨胀。"""
    _kf_msg_ids.add(msgid)
    _kf_msg_id_order.append(msgid)
    while len(_kf_msg_id_order) > MAX_KF_DEDUP:
        _kf_msg_ids.discard(_kf_msg_id_order.popleft())


def _kf_is_seen(msgid: str) -> bool:
    if not msgid:
        return False
    try:
        from core.redis_session import get_sync_redis
        r = get_sync_redis()
        if r is not None:
            key = "wecom:kf:seen"
            if r.sismember(key, msgid):
                return True
            # sadd 与 expire 一起下发，避免进程在两者之间退出导致 key 永不过期。
            pipe = r.pipeline()
            pipe.sadd(key, msgid)
            pipe.expire(key, 86400)
            pipe.execute()
            return False
    except Exception as e:
        logger.debug("客服消息去重回退到内存集合（Redis 不可用）: %s", e)
    if msgid in _kf_msg_ids:
        return True
    _kf_remember(msgid)
    return False


class WeComSignatureError(Exception):
    """企业微信回调验签失败：密文被篡改、Token 不匹配或缺少必要参数。"""


def _sha1_signature(token: str, timestamp: str, nonce: str, payload: str) -> str:
    text = "".join(sorted([token or "", timestamp, nonce, payload]))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def verify_signature(signature: str, timestamp: str, nonce: str, echostr: str) -> bool:
    if not signature:
        return False
    expect = _sha1_signature(settings.WECOM_TOKEN or "", timestamp, nonce, echostr)
    return hmac.compare_digest(expect, signature)


def _extract_encrypt(xml_text: str) -> str:
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return ""
    node = root.find("Encrypt")
    return (node.text or "").strip() if node is not None else ""


def decrypt_message(body: str, signature: str, timestamp: str, nonce: str) -> str:
    """解密回调密文；验签不通过一律抛 WeComSignatureError。

    这里绝不再回退到明文：过去失败时 `return body` 会让任意伪造的明文 XML
    直接进入 `_handle_kf_message`/`enqueue_reply`，等于把 Agent 变成一个对外
    开放的烧 token 接口，同时污染会话上下文与合规证据链。
    """
    if not settings.WECOM_ENCODING_AES_KEY:
        raise WeComSignatureError("未配置 WECOM_ENCODING_AES_KEY，无法解密回调")
    if not (signature and timestamp and nonce):
        raise WeComSignatureError("缺少 msg_signature/timestamp/nonce")

    encrypt = _extract_encrypt(body)
    if not encrypt:
        raise WeComSignatureError("回调报文里没有 <Encrypt> 节点")
    # 显式本地验签一次：wechatpy 内部也会验，但先自己验能在依赖缺失或版本差异时
    # 给出确定的拒绝语义，而不是把密文当明文继续往下走。
    expect = _sha1_signature(settings.WECOM_TOKEN or "", timestamp, nonce, encrypt)
    if not hmac.compare_digest(expect, signature):
        raise WeComSignatureError("msg_signature 校验失败")

    try:
        from wechatpy.enterprise.crypto import WeChatCrypto
    except ImportError as e:
        raise WeComSignatureError(f"wechatpy 未安装，无法解密回调: {e}") from e

    crypto = WeChatCrypto(
        settings.WECOM_TOKEN or "",
        settings.WECOM_ENCODING_AES_KEY or "",
        settings.WECOM_CORP_ID or "",
    )
    try:
        return crypto.decrypt_message(body, signature, timestamp, nonce)
    except Exception as e:
        raise WeComSignatureError(f"回调密文解密失败: {e}") from e


def decrypt_echostr(echostr: str, signature: str, timestamp: str, nonce: str) -> str:
    """安全模式下 URL 验证的 echostr 为 AES 密文，需解密后返回明文。"""
    from wechatpy.enterprise.crypto import WeChatCrypto
    crypto = WeChatCrypto(
        settings.WECOM_TOKEN or "",
        settings.WECOM_ENCODING_AES_KEY or "",
        settings.WECOM_CORP_ID or "",
    )
    xml = f"<xml><Encrypt><![CDATA[{echostr}]]></Encrypt></xml>"
    return crypto.decrypt_message(xml, signature, timestamp, nonce)


def parse_message(xml_text: str) -> dict:
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return {}
    def _text(name: str) -> str:
        node = root.find(name)
        return (node.text or "").strip() if node is not None else ""

    msg_types = [n.text or "" for n in root.findall("MsgType")]
    kf_msg_type = msg_types[-1].strip() if len(msg_types) > 1 else _text("MsgType")
    return {
        "type": _text("MsgType") or _text("msgtype"),
        "from": _text("FromUserName"),
        "content": _text("Content"),
        "event": _text("Event"),
        "event_type": _text("EventType"),
        "external_userid": _text("ExternalUserID"),
        "open_kfid": _text("OpenKfId"),
        "kf_token": _text("Token"),
        "kf_msg_type": kf_msg_type,
    }


@router.get("/wecom")
async def verify_wecom(timestamp: str = "", nonce: str = "", echostr: str = "", msg_signature: str = ""):
    if not verify_signature(msg_signature, timestamp, nonce, echostr):
        logger.warning("企业微信验证失败：签名不匹配")
        return Response(content="invalid signature", media_type="text/plain")

    plain = echostr
    if settings.WECOM_ENCODING_AES_KEY and echostr:
        try:
            plain = decrypt_echostr(echostr, msg_signature, timestamp, nonce)
            logger.info("企业微信 URL 验证成功，返回明文 echostr")
        except Exception as e:
            logger.warning("echostr 解密失败，按明文返回: %s", e)
    return Response(content=plain, media_type="text/plain")


async def _handle_kf_message(msg: dict) -> Response:
    kf_token = msg.get("kf_token") or ""
    open_kfid = msg.get("open_kfid") or ""
    if not kf_token:
        logger.warning("客服事件缺少 Token，无法拉取消息（检查回调是否走的安全模式）")
        return Response()
    try:
        messages = wecom_client.sync_kf_messages(kf_token, open_kfid)
    except Exception as e:
        logger.error("企业微信客服消息拉取失败: %s", e)
        return Response()
    logger.info("企业微信客服消息同步完成，共 %s 条", len(messages))
    for _m in messages:
        logger.debug(
            "客服消息明细: msgid=%s type=%s origin=%s external=%s",
            _m.get("msgid"), _m.get("msgtype"), _m.get("origin"), _m.get("external_userid"),
        )
    for item in messages:
        msgid = item.get("msgid") or ""
        if msgid and _kf_is_seen(msgid):
            logger.debug("客服消息重复，已跳过: msgid=%s", msgid)
            continue
        msgtype = item.get("msgtype") or ""
        if msgtype != "text":
            # 图片/语音/文件/视频等不自动回复，但必须显式记录而不是静默丢弃：
            # 静默 continue 会让客服侧表现为"已连接但客户发了消息没反应"，无从排查。
            logger.info(
                "客服收到非文本消息，仅记录不自动回复: msgid=%s type=%s origin=%s external=%s",
                msgid, msgtype, item.get("origin"), item.get("external_userid"),
            )
            continue
        if item.get("origin") not in (3, None):
            logger.debug(
                "客服消息非客户发送（origin=%s），跳过: msgid=%s", item.get("origin"), msgid
            )
            continue
        external_userid = item.get("external_userid") or ""
        content = (item.get("text") or {}).get("content") or ""
        if not external_userid or not content:
            logger.warning(
                "客服消息字段缺失，无法派发: msgid=%s external=%s content_len=%s",
                msgid, bool(external_userid), len(content),
            )
            continue
        try:
            from core.compliance_flow import compliance_flow
            tenant_id = default_tenant_id()
            session_id = tenant_session_key("wecom_kf", tenant_id, external_userid)
            compliance_flow.add_consent(
                session_id,
                source="wecom_kf",
                content="客户主动发起企业微信客服会话，视为同意本次会话内容处理",
                tenant_id=tenant_id,
            )
        except Exception as e:
            logger.warning("合规同意记录写入失败: %s", e)
        from core.reply_dispatcher import enqueue_reply
        enqueue_reply(
            channel="wecom_kf",
            external_id=external_userid,
            content=content,
            msg_id=msgid or "",
            session_id=session_id,
            open_kfid=item.get("open_kfid") or open_kfid,
            source="wecom_kf",
        )
    return Response()
@router.post("/wecom")
async def handle_wecom(request: Request):
    body = (await request.body()).decode("utf-8", errors="replace")
    query = request.query_params
    signature = query.get("msg_signature") or query.get("signature") or ""
    timestamp = query.get("timestamp") or ""
    nonce = query.get("nonce") or ""

    if "<Encrypt" in body:
        # 安全模式/兼容模式：密文回调，验签失败一律 403。
        try:
            body = decrypt_message(body, signature, timestamp, nonce)
        except WeComSignatureError as e:
            logger.warning("企业微信回调验签失败，已拒绝: %s", e)
            return Response(
                content="invalid signature", status_code=403, media_type="text/plain"
            )
    elif settings.WECOM_ENCODING_AES_KEY:
        # 已配置 AES 密钥却收到明文回调 —— 不可能来自企业微信，属于伪造请求。
        logger.warning("企业微信回调缺少密文（已配置 AES 密钥），已拒绝: len=%s", len(body))
        return Response(
            content="invalid signature", status_code=403, media_type="text/plain"
        )
    elif not settings.WECOM_ALLOW_PLAINTEXT_CALLBACK:
        # 明文模式企业微信不提供签名，默认关闭该通道，避免任意伪造客户消息进入。
        logger.warning("企业微信明文模式回调已被拒绝（WECOM_ALLOW_PLAINTEXT_CALLBACK=false）")
        return Response(
            content="plaintext callback disabled", status_code=403, media_type="text/plain"
        )
    else:
        logger.warning("企业微信明文模式回调已放行（无签名保护，建议改配 AES 密钥走安全模式）")

    msg = parse_message(body)
    logger.info("企业微信回调: event=%s type=%s event_type=%s external=%s", msg.get("event"), msg.get("type"), msg.get("event_type"), msg.get("external_userid") or msg.get("from") or "")
    logger.debug("企业微信回调原文(截断): %s", body[:600])
    logger.info("企业微信回调解析结果: %s", msg)
    from_user = msg.get("from") or ""

    if msg.get("event") == "kf_msg_or_event":
        return await _handle_kf_message(msg)
    if not from_user:
        return Response()

    if msg.get("type") == "event":
        try:
            from core.compliance_flow import compliance_flow
            tenant_id = default_tenant_id()
            session_id = tenant_session_key("wecom", tenant_id, from_user)
            compliance_flow.add_consent(
                session_id,
                source="wecom",
                content="添加企业微信授权",
                tenant_id=tenant_id,
            )
        except Exception as e:
            logger.warning("企业微信合规同意留痕失败: %s", e)
        logger.info("企业微信事件: %s from=%s", msg.get("event"), from_user)
        return Response()

    if msg.get("type") != "text" or not msg.get("content"):
        return Response()

    from core.reply_dispatcher import enqueue_reply
    enqueue_reply(
        channel="wecom",
        external_id=from_user,
        content=msg["content"],
        session_id=tenant_session_key(
            "wecom",
            default_tenant_id(),
            from_user,
        ),
        source="wecom",
    )
    return Response()


class WeComSendModel(BaseModel):
    userid: str
    content: str
    mode: str = "internal"


@admin_router.get("/wecom/status")
async def wecom_status():
    return wecom_client.status()


@admin_router.post("/wecom/test-send", dependencies=[Depends(require_admin)])
async def wecom_test_send(req: WeComSendModel):
    try:
        if req.mode == "kf":
            wecom_client.send_kf(req.userid, req.content)
        else:
            wecom_client.send_text(req.userid, req.content)
        return {"ok": True, "mode": req.mode, "userid": req.userid}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
