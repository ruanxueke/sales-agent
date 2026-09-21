"""Agent 工具层：按客户意图调用真实业务数据，结果交给 LLM 组织回复"""
from __future__ import annotations
from core import sql_compat as sqlite3  # SQL 统一指向 DATABASE_URL，避免与 ORM 分叉
from pathlib import Path

from config.settings import settings

DB_PATH = Path(settings.DATA_DIR) / "customers.db"

INTENT_RULES = [
    ("订单", "query_order"),
    ("物流", "query_shipment"),
    ("发货", "query_shipment"),
    ("发票", "query_invoice"),
    ("开票", "query_invoice"),
    ("付款链接", "payment_link"),
    ("怎么买", "payment_link"),
    ("怎么付", "payment_link"),
    ("课程信息", "query_course"),
    ("课程是什么", "query_course"),
    ("课程内容", "query_course"),
]


def _db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def query_order(session_id: str) -> str:
    if not session_id:
        return "未提供客户ID，无法查询订单"
    conn = _db()
    rows = conn.execute(
        "SELECT order_no, product_name, amount, status, created_at FROM orders WHERE session_id = ? ORDER BY id DESC LIMIT 5",
        (session_id,),
    ).fetchall()
    conn.close()
    if not rows:
        return "该客户暂无订单"
    return "；".join(
        f"{r['order_no']} {r['product_name']} ¥{r['amount']} 状态:{r['status']} 下单:{r['created_at']}"
        for r in rows
    )


def query_shipment(session_id: str) -> str:
    if not session_id:
        return "未提供客户ID，无法查询物流"
    conn = _db()
    rows = conn.execute(
        "SELECT s.id, s.order_id, s.carrier, s.tracking_no, s.status, o.order_no "
        "FROM shipments s LEFT JOIN orders o ON o.id = s.order_id "
        "WHERE o.session_id = ? ORDER BY s.id DESC LIMIT 5",
        (session_id,),
    ).fetchall()
    conn.close()
    if not rows:
        return "该客户暂无发货记录"
    return "；".join(
        f"{r['order_no']} 承运:{r['carrier'] or '暂无'} 单号:{r['tracking_no'] or '暂无'} 状态:{r['status']}"
        for r in rows
    )


def query_invoice(session_id: str) -> str:
    if not session_id:
        return "未提供客户ID，无法查询发票"
    conn = _db()
    rows = conn.execute(
        "SELECT i.invoice_no, i.amount, i.title, i.status, o.order_no "
        "FROM invoices i LEFT JOIN orders o ON o.id = i.order_id "
        "WHERE o.session_id = ? ORDER BY i.id DESC LIMIT 5",
        (session_id,),
    ).fetchall()
    conn.close()
    if not rows:
        return "该客户暂无开票记录"
    return "；".join(
        f"{r['order_no']} {r['invoice_no']} ¥{r['amount']} 抬头:{r['title'] or '暂无'} 状态:{r['status']}"
        for r in rows
    )


def payment_link(session_id: str = "") -> str:
    conn = _db()
    row = conn.execute(
        "SELECT title, amount, link FROM payment_links WHERE status = 'active' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        return "暂无有效付款链接"
    return f"{row['title']} ¥{row['amount']} {row['link']}"


def query_course(session_id: str = "") -> str:
    conn = _db()
    row = conn.execute(
        "SELECT product_name, price, selling_points, after_sales FROM product_knowledge WHERE active = 1 LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        return "暂无课程信息"
    return f"{row['product_name']}，{row['price']}。{row['selling_points']} 售后：{row['after_sales']}"


TOOLS = {
    "query_order": query_order,
    "query_shipment": query_shipment,
    "query_invoice": query_invoice,
    "payment_link": payment_link,
    "query_course": query_course,
}


def detect_intents(message: str) -> list[str]:
    found = []
    for word, tool in INTENT_RULES:
        if word in (message or ""):
            if tool not in found:
                found.append(tool)
    return found[:2]


def run_tools(message: str, session_id: str = "") -> list[dict]:
    calls = []
    for tool in detect_intents(message):
        try:
            result = TOOLS[tool](session_id)
            calls.append({"tool": tool, "result": result})
        except Exception as e:
            calls.append({"tool": tool, "result": f"工具执行失败: {e}"})
    return calls
