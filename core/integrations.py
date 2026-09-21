"""飞书/钉钉/ERP 集成占位：统一状态接口与接入点（密钥未配置时返回未启用）"""
from __future__ import annotations
from config.settings import settings


def status() -> dict:
    return {
        "feishu": {
            "configured": bool(settings.FEISHU_APP_ID and settings.FEISHU_APP_SECRET),
            "features": ["消息推送", "审批", "日程同步"],
            "note": "未配置 FEISHU_APP_ID/FEISHU_APP_SECRET",
        },
        "dingtalk": {
            "configured": bool(settings.DINGTALK_APP_KEY and settings.DINGTALK_APP_SECRET),
            "features": ["消息推送", "审批"],
            "note": "未配置 DINGTALK_APP_KEY/DINGTALK_APP_SECRET",
        },
        "erp": {
            "configured": bool(settings.ERP_API_URL and settings.ERP_API_KEY),
            "provider": settings.ERP_PROVIDER or "",
            "features": ["订单同步", "财务对账", "库存查询"],
            "note": "未配置 ERP_PROVIDER/ERP_API_URL/ERP_API_KEY",
        },
    }


def send_feishu_message(user_id: str, content: str) -> dict:
    if not status()["feishu"]["configured"]:
        return {"ok": False, "channel": "feishu", "error": "飞书未配置"}
    # 接入点：调用飞书 API 发送消息
    return {"ok": True, "channel": "feishu", "target": user_id, "content": content, "mode": "placeholder"}


def send_dingtalk_message(user_id: str, content: str) -> dict:
    if not status()["dingtalk"]["configured"]:
        return {"ok": False, "channel": "dingtalk", "error": "钉钉未配置"}
    return {"ok": True, "channel": "dingtalk", "target": user_id, "content": content, "mode": "placeholder"}
