"""销售公共常量：阶段、意向等级、档案字段"""

STAGES = [
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
STAGE_RANK = {stage: i for i, stage in enumerate(STAGES)}

PROFILE_FIELDS = {
    "nickname",
    "source",
    "name",
    "display_id",
    "phone",
    "wechat_id",
    "identity",
    "level",
    "goal",
    "budget",
    "interest",
    "stage",
    "intent_level",
    "intent_score",
    "sales_status",
    "notes",
    "next_follow_up",
}

STAGE_LABELS = {
    "new": "陌生/新线索",
    "understanding": "兴趣了解",
    "recommended": "意向明确",
    "quoted": "已报价",
    "high_intent": "高意向",
    "enrolled": "已报名",
    "won": "已成交",
    "after_sales": "售后",
    "lost": "流失",
}
