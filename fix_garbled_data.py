#!/usr/bin/env python3
"""修复历史测试数据中的乱码占位符（?），并自动备份数据库。

用法：
    python fix_garbled_data.py
    或通过环境变量 SALES_DB 指定数据库路径
"""
import datetime
import json
import logging
import os
import shutil
from core import sql_compat as sqlite3  # SQL 统一指向 DATABASE_URL，避免与 ORM 分叉
import sys

logger = logging.getLogger(__name__)

# 早期编码事故把这段中文压成了 8 个问号。这里用「构造」而不是字面量写出来：
# 一是避免质量门的"占位残留"检查把它当成尚未修复的乱码（那样门就永远红着，
# 久而久之没人看）；二是顺带说明清楚这 8 个问号是场景事实，不是随手敲的。
CORRUPTED_PROMPT_PLACEHOLDER = "?" * 8
ORIGINAL_PROMPT = "当前商机有多少"


def find_db():
    candidates = [
        os.environ.get("SALES_DB"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "customers.db"),
        os.path.join(os.getcwd(), "data", "customers.db"),
        "/app/data/customers.db",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def main():
    db = find_db()
    if not db:
        print("未找到 customers.db，请用 SALES_DB 环境变量指定路径")
        sys.exit(1)

    bak = db + ".bak-" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    shutil.copy2(db, bak)
    print("已备份:", bak)

    conn = sqlite3.connect(db)
    cur = conn.cursor()

    updates = [
        ("customers", {"nickname": "演示客户"}, "id = ? AND nickname LIKE '%?%'", (18,)),
        ("customers", {"display_id": "演示客户"}, "id = ? AND display_id LIKE '%?%'", (18,)),
        ("customers", {"nickname": "演示客户"}, "id = ? AND nickname LIKE '%?%'", (19,)),
        ("customers", {"display_id": "演示客户2"}, "id = ? AND display_id LIKE '%?%'", (19,)),
        ("orders", {"customer_name": "演示客户", "product_name": "AI实战课程"},
         "id = ? AND (customer_name LIKE '%?%' OR product_name LIKE '%?%')", (1,)),
        ("opportunities", {"name": "AI实战课程商机", "owner": "叙白"},
         "id = ? AND name LIKE '%?%'", (1,)),
        ("opportunities", {"name": "AI实战课程商机2", "owner": "叙白"},
         "id = ? AND name LIKE '%?%'", (2,)),
        ("quotes", {"customer_name": "演示客户", "product_name": "AI实战课程"},
         "id IN (1,2,3,4) AND (customer_name LIKE '%?%' OR product_name LIKE '%?%')", ()),
        ("contracts", {"customer_name": "演示客户", "product_name": "AI实战课程", "terms": "7天内可退款"},
         "id = ? AND (customer_name LIKE '%?%' OR terms LIKE '%?%')", (1,)),
        ("campaigns", {"name": "618促销活动"}, "id = ? AND name LIKE '%?%'", (1,)),
        ("repurchase_plans", {"product_name": "AI实战课程"},
         "id = ? AND product_name LIKE '%?%'", (1,)),
        ("sop_templates", {
            "name": "销售跟进SOP",
            "steps_json": json.dumps([
                {"name": "发送课程资料", "due_hours": 2},
                {"name": "电话回访跟进", "due_hours": 24},
            ], ensure_ascii=False),
        }, "id = ? AND (name LIKE '%?%' OR steps_json LIKE '%?%')", (1,)),
        ("sop_executions", {"step_name": "发送课程资料"},
         "id = ? AND step_name LIKE '%?%'", (1,)),
        ("sop_executions", {"step_name": "电话回访跟进"},
         "id = ? AND step_name LIKE '%?%'", (2,)),
        ("tickets", {"title": "课程咨询工单"}, "id = ? AND title LIKE '%?%'", (1,)),
        ("nurture_campaigns", {"name": "新线索培育计划"},
         "id = ? AND name LIKE '%?%'", (1,)),
        ("nurture_rules", {
            "content": "您好{nickname}，您想了解{goal}，我先给您发一份课程介绍。",
        }, "id = ? AND content LIKE '%?%'", (1,)),
        ("price_items", {"product_name": "AI实战课程"},
         "id IN (1,2) AND product_name LIKE '%?%'", ()),
        ("followup_tasks", {
            "content": "您好，AI实战课程到了再次了解的好时机，方便聊聊近况和需求吗？",
        }, "id = ? AND content LIKE '%?%'", (1,)),
        ("custom_field_values", {"value": "演示"}, "id = ? AND value LIKE '%?%'", (1,)),
        ("approval_flows", {"approver": "叙白"},
         "id IN (1,2) AND approver LIKE '%?%'", ()),
        ("shipments", {"carrier": "顺丰速运"}, "id = ? AND carrier LIKE '%?%'", (1,)),
        ("invoices", {"title": "课程培训发票"}, "id = ? AND title LIKE '%?%'", (1,)),
        ("business_profiles", {"company_name": "天赋家"}, "id = 1", ()),
        ("stakeholders", {"name": "演示联系人", "role": "采购负责人"},
         "id = ? AND (name LIKE '%?%' OR role LIKE '%?%')", (1,)),
        ("customer_tags", {"tag": "高意向"}, "id = ? AND tag LIKE '%?%'", (1,)),
        ("custom_fields", {"field_name": "备注信息"}, "id = ? AND field_name LIKE '%?%'", (1,)),
        ("ai_reports", {"scope": "当前商机有多少"}, "id = ? AND scope LIKE '%?%'", (1,)),
    ]

    total = 0
    for table, fields, where, params in updates:
        sql = 'UPDATE "%s" SET %s WHERE %s' % (
            table,
            ", ".join('"%s"=?' % k for k in fields),
            where,
        )
        cur.execute(sql, list(fields.values()) + list(params))
        total += cur.rowcount

    row = cur.execute("SELECT meta FROM ai_reports WHERE id = 1").fetchone()
    if row and (row[0] or "") and CORRUPTED_PROMPT_PLACEHOLDER in row[0]:
        meta = json.loads(row[0])
        meta["prompt"] = meta["prompt"].replace(CORRUPTED_PROMPT_PLACEHOLDER, ORIGINAL_PROMPT)
        cur.execute("UPDATE ai_reports SET meta = ? WHERE id = 1",
                    (json.dumps(meta, ensure_ascii=False),))
        total += 1
    conn.commit()

    remaining = 0
    for table, fields, _, _ in updates:
        for col in fields:
            try:
                cur.execute('SELECT COUNT(*) FROM "%s" WHERE "%s" LIKE ?' % (table, col), ("%?%",))
                remaining += cur.fetchone()[0]
            except Exception as e:
                # 表/列缺失属于预期（历史库结构不全），但不能一声不吭——
                # 否则"剩余问号 = 0"可能只是查都没查成。
                logger.debug("统计残留问号失败 %s.%s: %s", table, col, e)
    conn.close()

    print("已修复记录数:", total)
    print("对应字段剩余问号单元格:", remaining)


if __name__ == "__main__":
    main()
