"""多产品配置：定义产品信息、识别关键词、销售策略"""
from __future__ import annotations

# ===== 产品注册表 =====
PRODUCTS = {
    "ai_course": {
        "name": "AI 课程",
        "short_name": "AI 课程",
        "description": "AI 入门到进阶的系统课程",
        "keywords": [
            "ai", "人工智能", "课程", "学习", "培训", "chatgpt", "gpt",
            "深度学习", "机器学习", "提示词", "prompt", "大模型",
            "办公", "效率", "数据分析", "agent", "工作流",
            "入门", "零基础", "进阶", "变现", "赚钱",
        ],
        "welcome": "您好！想了解我们的 AI 课程，有什么具体想学的方向吗？",
    },
    "animation": {
        "name": "动画制作",
        "short_name": "动画",
        "description": "动画片制作服务/工具",
        "keywords": [
            "动画", "动画片", "动漫", "卡通", "制作动画",
            "视频", "短视频", "动画视频", "动画制作",
            "角色", "ip", "ip角色", "形象设计",
            "二维", "三维", "mg动画", "motion",
            "绘本", "故事", "儿童", "亲子",
            "自媒体", "抖音", "快手", "视频号",
        ],
        "welcome": "您好！看到您对动画制作感兴趣，想了解哪方面的呢？",
    },
}

# ===== 默认产品（无法识别时） =====
DEFAULT_PRODUCT = ""

# ===== 产品列表（用于提示选择） =====
PRODUCT_LIST_TEXT = "AI 课程 / 动画制作"

def detect_product(text: str) -> str:
    """从文本中检测产品意向，返回产品 key 或空字符串"""
    text_lower = text.lower()
    scores = {}
    for key, product in PRODUCTS.items():
        score = 0
        for kw in product["keywords"]:
            if kw in text_lower:
                score += 1
        scores[key] = score
    best = max(scores, key=scores.get)
    if scores[best] > 0:
        return best
    return ""

def get_product_info(product_key: str) -> dict:
    """获取产品信息"""
    return PRODUCTS.get(product_key, {})

def get_product_names() -> str:
    """返回所有产品名称，用于询问"""
    return " / ".join(p["short_name"] for p in PRODUCTS.values())
