"""视觉识别层：截图 -> qwen-vl 分析界面 -> 联系人/消息/输入框/风控提示。
未配置视觉模型时返回空结果，由上层进入安全暂停。
"""
from __future__ import annotations

import base64
import json
import logging
import re

import requests

from . import config

logger = logging.getLogger(__name__)

PROMPT = (
    "你是企业微信/微信 PC 客户端的界面识别助手。请分析这张截图并只输出 JSON，不要输出其他文字。\n"
    "JSON 字段："
    "{\"window_title\":\"...\",\"contacts\":[{\"name\":\"...\",\"x\":数字,\"y\":数字,\"unread\":true/false,\"last_preview\":\"...\"}],"
    "\"current_contact\":\"...\",\"messages\":[{\"sender\":\"对方/我/群成员名\",\"content\":\"...\",\"time\":\"...\"}],"
    "\"last_incoming\":{\"sender\":\"...\",\"content\":\"...\",\"time\":\"...\"},"
    "\"input_box\":{\"x\":数字,\"y\":数字},\"search_box\":{\"x\":数字,\"y\":数字},"
    "\"unread_count\":数字,\"is_group\":true/false,\"risk_warning\":\"...\"}\n"
    "要求：contacts 只列出左侧会话列表可见项；messages 只列当前会话可见消息；"
    "sender 用 对方/我 表示私聊，群聊用实际成员名；找不到的字段给 null 或空数组。"
)


def _to_data_url(image_bytes: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(image_bytes).decode("utf-8")


def _parse_result(text: str) -> dict:
    if not text:
        return {}
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except Exception as e:
        logger.warning("视觉识别结果解析失败: %s", e)
        return {}


def analyze_screenshot(image_bytes: bytes, instruction: str = "") -> dict:
    if not image_bytes or not config.DASHSCOPE_API_KEY:
        return {"ok": False, "note": "视觉模型未配置"}
    try:
        url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        headers = {"Authorization": f"Bearer {config.DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
        body = {
            "model": config.VISION_MODEL,
            "messages": [
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": _to_data_url(image_bytes)}},
                    {"type": "text", "text": instruction or PROMPT},
                ]},
            ],
        }
        resp = requests.post(url, headers=headers, json=body, timeout=45)
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        result = _parse_result(content)
        result["ok"] = bool(result.get("contacts") or result.get("messages") or result.get("current_contact"))
        return result
    except Exception as e:
        logger.error("视觉识别失败: %s", e)
        return {"ok": False, "error": str(e)[:200]}
