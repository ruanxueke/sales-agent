"""sync schema to ORM: backfill 14 missing tables and 9 missing columns (idempotent)

Revision ID: 0007_sync_schema_to_orm
Revises: 0006_add_display_id
Create Date: 2026-09-11

背景
----
`core/db.py::init_db()` 长期直接调用 `Base.metadata.create_all()`，而
`create_all` 只会创建「缺失的表」，**永远不会修改已存在的表**。
于是只要给已有表新增字段，线上库就不会跟进，代码一按新字段查询就报错——
这是迁移链与 ORM 长期脱节的根因，也是本次修复（P1-5）要解决的问题。

本迁移把 ORM 元数据与迁移链之间的差集一次性补齐，并刻意写成**幂等**形态：
表 / 字段 / 索引存在即跳过。原因是现网库里这些对象大多已由历史 `create_all`
建出来了，如果直接 `create_table` / `add_column`，升级会因为「已存在」而中断。
因此本迁移对下面两种库都安全：

- 由历史 `create_all` 建出的老库（对象已存在 -> 全部跳过）
- 由迁移链全新建出的库（对象缺失 -> 按 ORM 定义补齐）

补齐内容
--------
缺失的表（14 张）：
    bi_reports, channel_messages, channel_sessions, conversation_scores,
    dispatch_rules, marketing_journeys, moderation_rules,
    optimization_suggestions, personal_wechat_bridge_instances,
    personal_wechat_reply_tasks, prompt_versions, route_rules,
    sales_workflow_executions, sales_workflows

缺失的字段（5 张已有表 / 9 个字段）：
    audit_logs.category, audit_logs.level
    customers.product
    knowledge_versions.reviewed_at, knowledge_versions.reviewed_by,
    knowledge_versions.status
    leads.product, leads.tenant_id
    orders.tenant_id

数据回填
--------
`leads.tenant_id` / `orders.tenant_id` 在代码里被用于**等值过滤**
（`core/lead.py`、`core/commercial.py`、`core/sales_flow.py`），
NULL 不会命中 `tenant_id = 0`，所以新增这两列后必须把历史行回填到
`DEFAULT_TENANT_ID`（默认 0），否则老线索/老订单会在列表里凭空消失。
回填租户号可用环境变量 `DEFAULT_TENANT_ID` 覆盖。

注意：本迁移只做「补齐」，不做任何删列/改类型，可安全重复执行。
"""
from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op

revision = "0007_sync_schema_to_orm"
down_revision = "0006_add_display_id"
branch_labels = None
depends_on = None

S = sa.String
T = sa.Text
I = sa.Integer
F = sa.Float
B = sa.Boolean

# 表名 -> (列定义, 索引定义)
#   列定义: (列名, 类型, 是否 NOT NULL)
#   索引定义: (列名, 是否唯一)，索引名统一为 ix_<表名>_<列名>
NEW_TABLES: dict[str, tuple[list[tuple[str, sa.types.TypeEngine, int]], list[tuple[str, int]]]] = {
    "bi_reports": (
        [
            ("tenant_id", I(), 0), ("name", S(128), 0), ("metric", S(32), 0),
            ("dimension", S(32), 0), ("days", I(), 0), ("filters_json", T(), 0),
            ("created_by", S(64), 0), ("created_at", S(32), 0), ("updated_at", S(32), 0),
        ],
        [("tenant_id", 0), ("name", 0)],
    ),
    "channel_messages": (
        [
            ("tenant_id", I(), 0), ("session_id", I(), 1), ("channel", S(32), 0),
            ("direction", S(8), 0), ("content", T(), 0), ("msg_type", S(16), 0),
            ("created_at", S(32), 0),
        ],
        [("tenant_id", 0), ("session_id", 0)],
    ),
    "channel_sessions": (
        [
            ("tenant_id", I(), 0), ("channel", S(32), 0), ("external_id", S(128), 0),
            ("session_key", S(128), 0), ("customer_id", I(), 0), ("lead_id", I(), 0),
            ("nickname", S(128), 0), ("status", S(32), 0), ("priority", I(), 0),
            ("route_target", S(32), 0), ("assigned_agent", S(64), 0),
            ("source_page", S(255), 0), ("created_at", S(32), 0),
            ("updated_at", S(32), 0), ("closed_at", S(32), 0),
        ],
        [
            ("channel", 0), ("external_id", 0), ("session_key", 0), ("customer_id", 0),
            ("lead_id", 0), ("status", 0), ("priority", 0), ("tenant_id", 0),
        ],
    ),
    "conversation_scores": (
        [
            ("session_id", S(128), 0), ("customer_id", I(), 0), ("product", S(32), 0),
            ("conversion_score", I(), 0), ("compliance_score", I(), 0),
            ("satisfaction_score", I(), 0), ("response_score", I(), 0),
            ("total_score", I(), 0), ("score_details", T(), 0),
            ("prompt_version_id", I(), 0), ("experiment_id", I(), 0),
            ("experiment_variant", S(32), 0), ("created_at", S(32), 0),
        ],
        [
            ("session_id", 0), ("customer_id", 0), ("product", 0),
            ("prompt_version_id", 0), ("experiment_id", 0),
        ],
    ),
    "dispatch_rules": (
        [
            ("tenant_id", I(), 0), ("name", S(128), 0), ("strategy", S(32), 0),
            ("enabled", B(), 0), ("params_json", T(), 0), ("created_at", S(32), 0),
            ("updated_at", S(32), 0),
        ],
        [("tenant_id", 0), ("name", 0), ("enabled", 0)],
    ),
    "marketing_journeys": (
        [
            ("tenant_id", I(), 0), ("name", S(128), 0), ("trigger", S(32), 0),
            ("nodes_json", T(), 0), ("enabled", B(), 0), ("daily_limit", I(), 0),
            ("created_at", S(32), 0), ("updated_at", S(32), 0),
        ],
        [("tenant_id", 0), ("name", 0)],
    ),
    "moderation_rules": (
        [
            ("tenant_id", I(), 0), ("name", S(128), 0), ("keywords", T(), 0),
            ("action", S(16), 0), ("enabled", B(), 0), ("created_at", S(32), 0),
            ("updated_at", S(32), 0),
        ],
        [("tenant_id", 0), ("name", 0)],
    ),
    "optimization_suggestions": (
        [
            ("suggestion_type", S(32), 0), ("category", S(64), 0), ("title", S(255), 0),
            ("description", T(), 0), ("current_value", T(), 0), ("suggested_value", T(), 0),
            ("impact_score", F(), 0), ("data_basis", T(), 0), ("status", S(32), 0),
            ("applied_at", S(32), 0),
        ],
        [("suggestion_type", 0), ("status", 0)],
    ),
    "personal_wechat_bridge_instances": (
        [
            ("instance_id", S(128), 1), ("tenant_id", I(), 0), ("account_id", S(128), 0),
            ("status", S(24), 0), ("mode", S(16), 0), ("auto_discover_contacts", B(), 0),
            ("notify_on_message", B(), 0), ("recognition_enabled", B(), 0),
            ("detect_wechat_login", B(), 0), ("wechat_login_detected", B(), 0),
            ("poll_interval_seconds", I(), 0), ("last_message_at", S(32), 0),
            ("last_reply_at", S(32), 0), ("last_error", T(), 0), ("detail_json", T(), 0),
            ("last_seen", S(32), 0), ("updated_at", S(32), 0),
        ],
        [
            ("instance_id", 1), ("tenant_id", 0), ("account_id", 0),
            ("status", 0), ("last_seen", 0),
        ],
    ),
    "personal_wechat_reply_tasks": (
        [
            ("task_id", S(64), 1), ("tenant_id", I(), 0), ("source_message_id", S(160), 0),
            ("account_id", S(128), 0), ("session_id", I(), 0), ("target_type", S(16), 0),
            ("target_name", S(128), 0), ("target_username", S(128), 0), ("content", T(), 0),
            ("mode", S(16), 0), ("status", S(24), 0), ("error", T(), 0),
            ("claimed_by", S(128), 0), ("claimed_at", S(32), 0),
            ("lease_expires_at", S(32), 0), ("expires_at", S(32), 0), ("ack_at", S(32), 0),
            ("created_at", S(32), 0), ("updated_at", S(32), 0),
        ],
        [
            ("task_id", 1), ("tenant_id", 0), ("source_message_id", 0), ("account_id", 0),
            ("session_id", 0), ("target_username", 0), ("mode", 0), ("status", 0),
            ("lease_expires_at", 0), ("expires_at", 0), ("created_at", 0),
        ],
    ),
    "prompt_versions": (
        [
            ("version", I(), 0), ("content", T(), 0), ("description", S(255), 0),
            ("is_active", B(), 0), ("total_conversations", I(), 0), ("avg_score", F(), 0),
            ("conversion_rate", F(), 0), ("avg_turns", F(), 0),
            ("compliance_violations", I(), 0), ("created_at", S(32), 0),
            ("activated_at", S(32), 0), ("deactivated_at", S(32), 0),
        ],
        [("version", 0), ("is_active", 0)],
    ),
    "route_rules": (
        [
            ("tenant_id", I(), 0), ("name", S(128), 0), ("priority", I(), 0),
            ("condition_json", T(), 0), ("target", S(32), 0), ("enabled", B(), 0),
            ("created_at", S(32), 0), ("updated_at", S(32), 0),
        ],
        [("tenant_id", 0), ("name", 0)],
    ),
    "sales_workflow_executions": (
        [
            ("workflow_id", I(), 1), ("tenant_id", I(), 0), ("context_json", T(), 0),
            ("status", S(32), 0), ("result_json", T(), 0), ("started_at", S(32), 0),
            ("finished_at", S(32), 0),
        ],
        [("tenant_id", 0), ("workflow_id", 0), ("status", 0)],
    ),
    "sales_workflows": (
        [
            ("tenant_id", I(), 0), ("name", S(128), 0), ("trigger", S(32), 0),
            ("enabled", B(), 0), ("nodes_json", T(), 0), ("created_at", S(32), 0),
            ("updated_at", S(32), 0),
        ],
        [("tenant_id", 0), ("name", 0), ("trigger", 0), ("enabled", 0)],
    ),
}

# 已有表需要补的列：(表名, [(列名, 类型, 是否 NOT NULL)])
ADD_COLUMNS: list[tuple[str, list[tuple[str, sa.types.TypeEngine, int]]]] = [
    ("audit_logs", [("category", S(32), 0), ("level", S(16), 0)]),
    ("customers", [("product", S(32), 0)]),
    (
        "knowledge_versions",
        [("reviewed_at", S(32), 0), ("reviewed_by", S(64), 0), ("status", S(16), 0)],
    ),
    ("leads", [("product", S(32), 0), ("tenant_id", I(), 0)]),
    ("orders", [("tenant_id", I(), 0)]),
]

# 补列后需要同步补建的索引：(表名, [(索引名, [列名], 是否唯一)])
ADD_INDEXES: dict[str, list[tuple[str, list[str], bool]]] = {
    "customers": [("ix_customers_product", ["product"], False)],
    "leads": [
        ("ix_leads_product", ["product"], False),
        ("ix_leads_tenant_id", ["tenant_id"], False),
    ],
    "orders": [("ix_orders_tenant_id", ["tenant_id"], False)],
}

# 新增租户列后需要回填的历史数据：(表名, 列名)
TENANT_BACKFILL: list[tuple[str, str]] = [("leads", "tenant_id"), ("orders", "tenant_id")]

# downgrade 时需要删除的、由本迁移新增的字段：(表名, [列名])
DROP_COLUMNS: list[tuple[str, list[str]]] = [
    ("orders", ["tenant_id"]),
    ("leads", ["product", "tenant_id"]),
    ("knowledge_versions", ["reviewed_at", "reviewed_by", "status"]),
    ("customers", ["product"]),
    ("audit_logs", ["category", "level"]),
]


def _add_columns_sql(table: str, table_columns: list[tuple[str, str]]) -> list[sa.Column]:
    return [sa.Column(name, typ, nullable=not notnull) for name, typ, notnull in table_columns]


def _table_names(inspector: sa.Inspector) -> set[str]:
    return set(inspector.get_table_names())


def _column_names(inspector: sa.Inspector, table: str) -> set[str]:
    try:
        return {col["name"] for col in inspector.get_columns(table)}
    except Exception:  # noqa: BLE001 - 表不存在时视为无列，交由后续分支处理
        return set()


def _index_names(inspector: sa.Inspector, table: str) -> set[str]:
    try:
        return {ix["name"] for ix in inspector.get_indexes(table) if ix.get("name")}
    except Exception:  # noqa: BLE001
        return set()


def _create_table(table: str) -> None:
    columns, indexes = NEW_TABLES[table]
    op.create_table(
        table,
        sa.Column("id", I(), primary_key=True, autoincrement=True),
        *_add_columns_sql(table, columns),
    )
    for column, unique in indexes:
        op.create_index(f"ix_{table}_{column}", table, [column], unique=bool(unique))


def upgrade() -> None:
    bind = op.get_bind()

    # 1) 缺失的表：按 ORM 定义建表 + 建索引
    existing = _table_names(sa.inspect(bind))
    for table in NEW_TABLES:
        if table in existing:
            continue
        _create_table(table)

    # 2) 已存在的表：补齐缺失索引（历史 create_all 可能漏建，或表是手工建的）
    existing = _table_names(sa.inspect(bind))
    for table, (_columns, indexes) in NEW_TABLES.items():
        if table not in existing:
            continue
        have = _index_names(sa.inspect(bind), table)
        for column, unique in indexes:
            index_name = f"ix_{table}_{column}"
            if index_name in have:
                continue
            op.create_index(index_name, table, [column], unique=bool(unique))

    # 3) 已存在的表：补齐缺失字段
    existing = _table_names(sa.inspect(bind))
    for table, columns in ADD_COLUMNS:
        if table not in existing:
            continue
        have = _column_names(sa.inspect(bind), table)
        for name, typ, notnull in columns:
            if name in have:
                continue
            op.add_column(table, sa.Column(name, typ, nullable=not notnull))

    # 4) 补列后同步补索引
    existing = _table_names(sa.inspect(bind))
    for table, indexes in ADD_INDEXES.items():
        if table not in existing:
            continue
        have = _index_names(sa.inspect(bind), table)
        for index_name, columns, unique in indexes:
            if index_name in have:
                continue
            op.create_index(index_name, table, columns, unique=unique)

    # 5) 回填历史行的租户号（NULL 不会命中 tenant_id 等值查询）
    try:
        default_tenant_id = int(os.environ.get("DEFAULT_TENANT_ID") or 0)
    except (TypeError, ValueError):
        default_tenant_id = 0
    existing = _table_names(sa.inspect(bind))
    for table, column in TENANT_BACKFILL:
        if table not in existing:
            continue
        if column not in _column_names(sa.inspect(bind), table):
            continue
        bind.execute(
            sa.text(f"UPDATE {table} SET {column} = :tid WHERE {column} IS NULL"),
            {"tid": default_tenant_id},
        )


def downgrade() -> None:
    """回滚：删除本迁移新增的字段与表。注意 —— 新表内的数据会一并丢失。"""
    bind = op.get_bind()
    existing = _table_names(sa.inspect(bind))

    for table, index_names in [
        ("orders", ["ix_orders_tenant_id"]),
        ("leads", ["ix_leads_tenant_id", "ix_leads_product"]),
        ("customers", ["ix_customers_product"]),
    ]:
        if table not in existing:
            continue
        have = _index_names(sa.inspect(bind), table)
        for index_name in index_names:
            if index_name in have:
                op.drop_index(index_name, table_name=table)

    for table, columns in DROP_COLUMNS:
        if table not in existing:
            continue
        have = _column_names(sa.inspect(bind), table)
        for column in columns:
            if column in have:
                op.drop_column(table, column)

    existing = _table_names(sa.inspect(bind))
    for table in reversed(list(NEW_TABLES)):
        if table in existing:
            op.drop_table(table)
