"""销售关键信息提取与阶段推进规则（规则版，稳定可复现）"""
from __future__ import annotations
import re

_STAGE_ORDER = [
    "new",
    "understanding",
    "recommended",
    "quoted",
    "high_intent",
    "enrolled",
    "won",
    "after_sales",
    "lost",
]
STAGE_RANK = {stage: i for i, stage in enumerate(_STAGE_ORDER)}

PHONE_RE = re.compile(r"1[3-9]\d{9}")
BUDGET_RE = re.compile(r"预算\s*[:：]?\s*(\d+(?:\.\d+)?)")
WECHAT_RE = re.compile(r"(?:微信|vx|wx)\s*(?:是|为|号|[:：])?\s*([A-Za-z][A-Za-z0-9_-]{5,})", re.IGNORECASE)
NAME_RE = re.compile(r"我叫\s*([\u4e00-\u9fa5A-Za-z0-9]{1,20})")

ENTERPRISE_WORDS = ["企业", "公司", "团队", "内训", "机构", "单位", "我们部门"]
PERSONAL_WORDS = ["个人", "自己学", "自己用", "个人学"]
ZERO_LEVEL_WORDS = ["零基础", "小白", "没基础", "从零", "一点都不懂"]
BASIC_LEVEL_WORDS = ["有基础", "有经验", "学过", "有点基础", "熟悉", "接触过"]

GOAL_KEYWORDS = {
    "自媒体创作": ["自媒体", "内容创作", "短视频", "小红书", "抖音", "视频号", "写作", "爆款"],
    "办公提效": ["办公", "效率", "ppt", "excel", "word", "报告", "表格", "文档"],
    "数据分析": ["数据分析", "数据看板", "报表", "分析数据"],
    "商业应用": ["变现", "获客", "营销", "引流", "成交", "带货", "创业"],
    "企业赋能": ["企业培训", "团队赋能", "内训", "给团队", "给员工", "公司用"],
    "兴趣了解": ["兴趣", "好奇"],
}

INTEREST_KEYWORDS = {
    "AI入门": ["入门", "认知", "零基础学ai", "小白课"],
    "AI应用": ["chatgpt", "提示词", "ai办公", "ai写作", "ai画图", "应用"],
    "AI进阶": ["agent", "工作流", "rag", "开发", "编程", "进阶"],
    "AI商业": ["营销", "获客", "变现", "商业", "创业"],
    "B端企业": ["企业内训", "团队", "内训", "b端"],
}

PRICE_WORDS = ["多少钱", "价格", "报价", "费用", "收费", "价位"]
PROMO_WORDS = ["优惠", "折扣", "套餐", "活动", "便宜", "降价"]
PAYMENT_WORDS = ["怎么付款", "付款", "支付", "转账", "发票", "开票", "怎么买"]
ENROLL_WORDS = ["报名", "购买", "下单", "想买", "开通", "我要报"]


def extract_profile(text: str) -> dict:
    """从客户消息中提取可结构化信息"""
    lowered = text.lower()
    result = {
        "name": "",
        "phone": "",
        "wechat_id": "",
        "identity": "",
        "level": "",
        "goal": "",
        "budget": "",
        "interest": "",
        "intent_score": 0,
        "enroll": False,
        "high_intent": False,
    }

    name_match = NAME_RE.search(text)
    if name_match:
        result["name"] = name_match.group(1).strip()

    phone_match = PHONE_RE.search(text)
    if phone_match:
        result["phone"] = phone_match.group(0)

    wechat_match = WECHAT_RE.search(text)
    if wechat_match:
        result["wechat_id"] = wechat_match.group(1)

    budget_match = BUDGET_RE.search(text)
    if budget_match:
        result["budget"] = budget_match.group(1)

    if any(w in text for w in ENTERPRISE_WORDS):
        result["identity"] = "企业"
    elif any(w in text for w in PERSONAL_WORDS):
        result["identity"] = "个人"

    if any(w in text for w in ZERO_LEVEL_WORDS):
        result["level"] = "零基础"
    elif any(w in text for w in BASIC_LEVEL_WORDS):
        result["level"] = "有基础"

    for goal, words in GOAL_KEYWORDS.items():
        if any(w in lowered for w in words):
            result["goal"] = goal
            break

    for interest, words in INTEREST_KEYWORDS.items():
        if any(w in lowered for w in words):
            result["interest"] = interest
            break

    price_hit = any(w in text for w in PRICE_WORDS)
    promo_hit = any(w in text for w in PROMO_WORDS)
    payment_hit = any(w in text for w in PAYMENT_WORDS)
    enroll_hit = any(w in text for w in ENROLL_WORDS)

    result["enroll"] = enroll_hit
    result["high_intent"] = price_hit or promo_hit or payment_hit
    result["intent_score"] = int(price_hit) + int(promo_hit) + int(payment_hit) + int(enroll_hit) * 2
    return result



def detect_customer_product(text: str, source: str = "") -> str:
    """从客户消息中检测产品意向
    返回产品 key（如 'ai_course'、'animation'）或空字符串
    """
    try:
        from config.products import detect_product
        return detect_product(text)
    except Exception:
        return ""
def compute_stage(profile: dict, extracted: dict) -> str:
    """根据客户档案和本次提取结果计算应推进到的阶段"""
    rank = STAGE_RANK
    current = profile.get("stage") or "new"
    best = current

    if extracted.get("enroll"):
        candidate = "enrolled"
        if rank[candidate] > rank[best]:
            best = candidate
    if extracted.get("high_intent"):
        candidate = "high_intent"
        if rank[candidate] > rank[best]:
            best = candidate
    if extracted.get("goal") or extracted.get("interest"):
        candidate = "recommended"
        if rank[candidate] > rank[best]:
            best = candidate
    if extracted.get("identity") or extracted.get("level"):
        candidate = "understanding"
        if rank[candidate] > rank[best]:
            best = candidate
    return best


def compute_intent_level(stage: str, intent_score: int = 0) -> str:
    """把销售阶段和意向分归一成 5 层意向等级"""
    if stage in ("enrolled", "won", "after_sales"):
        return "L5 已报名/已成交"
    if stage == "high_intent" or intent_score >= 3:
        return "L4 高意向"
    if stage in ("recommended", "quoted") or intent_score >= 1:
        return "L3 意向明确"
    if stage == "understanding":
        return "L2 兴趣了解"
    return "L1 陌生/观望"


def build_profile_text(profile: dict) -> str:
    """生成给模型的客户档案摘要"""
    labels = [
        ("姓名", "name"),
        ("电话", "phone"),
        ("微信号", "wechat_id"),
        ("身份", "identity"),
        ("基础", "level"),
        ("目标", "goal"),
        ("预算", "budget"),
        ("兴趣课程", "interest"),
        ("意向产品", "product"),
        ("意向等级", "intent_level"),
        ("备注", "notes"),
    ]
    parts = [f"{label}: {profile.get(key) or '未提供'}" for label, key in labels]
    return "\n".join(parts)
