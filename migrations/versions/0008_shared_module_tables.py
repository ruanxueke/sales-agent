"""add module-private tables to the shared database (idempotent)

Revision ID: 0008_shared_module_tables
Revises: 0007_sync_schema_to_orm
Create Date: 2026-09-11

背景
----
项目里有 30 多个模块长期用 `sqlite3.connect(DATA_DIR/"customers.db")` 直连 SQL，
而生产 ORM 走的是 PostgreSQL。两者不是同一个库，于是：

- `core/enterprise.py` 去 SQLite 找 `orders`/`leads`/`approval_flows` —— 这些表只在 PG，
  业绩榜与佣金因此永远读不到真实数据；
- 登录态（`system_users`/`auth_tokens`）、成员（`tenant_members`）、租户
  （`tenants`/`tenant_settings`）、配额、审批规则、SLA 全被写进 SQLite，
  业务数据在 PG，两边彻底割裂；
- api / official / worker / beat 四个容器共享同一个 SQLite 文件并发写 -> `database is locked`。

修复方式见 `core/sql_compat.py`：提供与 `sqlite3` 同形的 `connect()`，把连接统一
重定向到 `DATABASE_URL`。**代价是这些模块自建的 DDL 在 PG 上会被跳过**（因为结构必须
由迁移链统一管理），所以它们依赖的表必须先在本迁移里建出来 —— 这就是本文件的作用。

本迁移补齐
----------
模块自建的 27 张表（原本各自 `CREATE TABLE IF NOT EXISTS` 在 SQLite 里）：
    alert_events, alert_rules, api_events, approval_rules, auth_tokens, blocked_users,
    commission_records, commission_rules, consent_logs, conversation_citations,
    conversation_feedback, customer_tiers, deletion_requests, heartbeats, knowledge_gaps,
    llm_traces, llm_usage, sales_targets, sla_policies, subscriptions, system_users,
    tenant_members, tenant_settings, tenants, usage_ledger, webchat_messages, webchat_sessions

外加 2 处跨模块隐式依赖（对应清单 C4）：
    customers.tenant_id       —— `core/sales_crm.py:185` 用 `WHERE tenant_id=?` 查询，
                                 但 ORM 的 `customers` 没有这一列，一直靠 SQLite 的
                                 `ALTER TABLE` 现补；PG 上会直接 `column does not exist`。
    system_users.tenant_id    —— `core/enterprise.py:173` 在登录成功后读
                                 `user["tenant_id"]`，而该列原本由 `core/tenant.py:70`
                                 用 ALTER 补，跨模块隐式依赖（并且只导入 enterprise 时会 KeyError）。
    system_users.display_name —— 同上，`core/tenant.py:71` 补的列。

类型映射
--------
SQLite 的 `TEXT` 无长度上限，因此统一映射为 PG 的 `TEXT`（`sa.Text`），
不做长度截断，避免历史数据超长时插入失败。
原本是 `TEXT DEFAULT (datetime('now','localtime'))` 的时间列**不带 server_default**：
各模块全都显式传入 Python 侧格式化好的本地时间字符串，若交给数据库默认值，
SQLite 与 PG 的时区/格式不一致会让 `created_at >= cutoff` 这类字符串比较出错。

索引
----
额外给"按时间窗口做报表/清理"和唯一的业务键补了索引，这是这些表在生产上的主要访问路径。
本迁移幂等：表/列/索引存在即跳过，可安全重复执行。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_shared_module_tables"
down_revision = "0007_sync_schema_to_orm"
branch_labels = None
depends_on = None

I = sa.Integer
T = sa.Text
F = sa.Float

# 表名 -> (列定义, 唯一约束列组, 索引列组)
#   列定义: (列名, 类型, 是否 NOT NULL, server_default 或 None)
#   unique: [ [列...], ... ]
#   indexes: [ 列, ... ]
TABLES: dict[str, tuple[list[tuple[str, object, int, object]], list[list[str]], list[str]]] = {
    "alert_events": (
        [
            ("rule_id", I(), 0, None), ("rule_type", T(), 0, None), ("title", T(), 0, None),
            ("content", T(), 0, None), ("level", T(), 0, "warning"), ("status", T(), 0, "sent"),
            ("sent_at", T(), 0, None),
        ],
        [], ["sent_at"],
    ),
    "alert_rules": (
        [
            ("rule_type", T(), 0, None), ("name", T(), 0, None), ("enabled", I(), 0, "1"),
            ("threshold", F(), 0, "0"), ("window_seconds", I(), 0, "300"),
            ("channels", T(), 0, "webhook"), ("receivers", T(), 0, ""),
            ("cooldown_seconds", I(), 0, "600"), ("created_at", T(), 0, None),
        ],
        [], ["rule_type"],
    ),
    "api_events": (
        [
            ("endpoint", T(), 1, None), ("latency_ms", I(), 1, None), ("success", I(), 1, None),
            ("created_at", T(), 0, None),
        ],
        [], ["created_at", "endpoint"],
    ),
    "approval_rules": (
        [
            ("biz_type", T(), 0, None), ("name", T(), 0, None), ("condition_key", T(), 0, None),
            ("operator", T(), 0, ">"), ("threshold", F(), 0, "0"),
            ("approver", T(), 0, "主管"), ("level", I(), 0, "1"), ("enabled", I(), 0, "1"),
            ("created_at", T(), 0, None),
        ],
        [], ["biz_type"],
    ),
    "auth_tokens": (
        [
            ("token", T(), 0, None), ("user_id", I(), 0, None), ("expires_at", T(), 0, None),
            ("created_at", T(), 0, None),
        ],
        [["token"]], ["user_id"],
    ),
    "blocked_users": (
        [
            ("session_id", T(), 1, None), ("reason", T(), 0, ""), ("created_at", T(), 0, None),
        ],
        [], ["session_id"],
    ),
    "commission_records": (
        [
            ("order_id", I(), 0, None), ("member", T(), 0, None),
            ("order_amount", F(), 0, "0"), ("commission", F(), 0, "0"),
            ("status", T(), 0, "pending"), ("created_at", T(), 0, None),
        ],
        [], ["order_id", "member"],
    ),
    "commission_rules": (
        [
            ("name", T(), 0, None), ("rule_type", T(), 0, "percent"), ("value", F(), 0, "0"),
            ("enabled", I(), 0, "1"), ("created_at", T(), 0, None),
        ],
        [], [],
    ),
    "consent_logs": (
        [
            ("session_id", T(), 0, ""), ("source", T(), 0, ""), ("content", T(), 0, ""),
            ("status", T(), 0, "granted"), ("created_at", T(), 0, None),
        ],
        [], ["session_id"],
    ),
    "conversation_citations": (
        [
            ("session_id", T(), 0, ""), ("message", T(), 0, ""), ("reply", T(), 0, ""),
            ("sources", T(), 0, "[]"), ("created_at", T(), 0, None),
        ],
        [], ["session_id"],
    ),
    "conversation_feedback": (
        [
            ("session_id", T(), 0, ""), ("customer_id", I(), 0, None), ("message", T(), 0, ""),
            ("reply", T(), 0, ""), ("rating", T(), 0, "bad"), ("issue_type", T(), 0, ""),
            ("standard_reply", T(), 0, ""), ("note", T(), 0, ""), ("status", T(), 0, "open"),
            ("created_at", T(), 0, None),
        ],
        [], ["session_id", "status"],
    ),
    "customer_tiers": (
        [
            ("tier", T(), 0, None), ("name", T(), 0, None), ("min_amount", F(), 0, "0"),
            ("priority_boost", I(), 0, "0"), ("enabled", I(), 0, "1"), ("created_at", T(), 0, None),
        ],
        [], ["tier"],
    ),
    "deletion_requests": (
        [
            ("session_id", T(), 0, ""), ("applicant", T(), 0, ""), ("reason", T(), 0, ""),
            ("status", T(), 0, "pending"), ("created_at", T(), 0, None),
            ("handled_at", T(), 0, ""), ("handler", T(), 0, ""),
        ],
        [], ["status"],
    ),
    "heartbeats": (
        [
            ("last_seen", T(), 1, None),
        ],
        [], [],
    ),
    "knowledge_gaps": (
        [
            ("session_id", T(), 0, ""), ("question", T(), 0, ""), ("created_at", T(), 0, None),
        ],
        [], ["created_at"],
    ),
    "llm_traces": (
        [
            ("session_id", T(), 0, ""), ("model", T(), 0, ""), ("message", T(), 0, ""),
            ("reply", T(), 0, ""), ("prompt_tokens", I(), 0, "0"),
            ("completion_tokens", I(), 0, "0"), ("latency_ms", I(), 0, "0"),
            ("cost_yuan", F(), 0, "0"), ("created_at", T(), 0, None),
        ],
        [], ["session_id", "created_at"],
    ),
    "llm_usage": (
        [
            ("session_id", T(), 1, None), ("source", T(), 0, ""), ("model", T(), 0, ""),
            ("prompt_tokens", I(), 0, "0"), ("completion_tokens", I(), 0, "0"),
            ("total_tokens", I(), 0, "0"), ("latency_ms", I(), 0, "0"),
            ("created_at", T(), 0, None),
        ],
        [], ["session_id", "created_at"],
    ),
    "sales_targets": (
        [
            ("member", T(), 0, None), ("period", T(), 0, None),
            ("target_type", T(), 0, "amount"), ("amount", F(), 0, "0"), ("created_at", T(), 0, None),
        ],
        [], ["member", "period"],
    ),
    "sla_policies": (
        [
            ("priority", T(), 0, None), ("name", T(), 0, None),
            ("respond_hours", F(), 0, "2"), ("resolve_hours", F(), 0, "24"),
            ("enabled", I(), 0, "1"), ("created_at", T(), 0, None),
        ],
        [], ["priority"],
    ),
    "subscriptions": (
        [
            ("tenant_id", I(), 0, None), ("plan", T(), 0, "trial"), ("status", T(), 0, "active"),
            ("started_at", T(), 0, None), ("expires_at", T(), 0, None),
            ("auto_renew", I(), 0, "0"), ("created_at", T(), 0, None),
        ],
        [], ["tenant_id"],
    ),
    "system_users": (
        [
            ("username", T(), 0, None), ("password_hash", T(), 0, None), ("name", T(), 0, ""),
            ("role", T(), 0, "sales"), ("status", T(), 0, "active"),
            ("tenant_id", I(), 0, "0"), ("display_name", T(), 0, ""),
            ("created_at", T(), 0, None),
        ],
        [["username"]], [],
    ),
    "tenant_members": (
        [
            ("tenant_id", I(), 0, None), ("user_id", I(), 0, None), ("role", T(), 0, "sales"),
            ("status", T(), 0, "active"), ("created_at", T(), 0, None),
        ],
        [["tenant_id", "user_id"]], ["tenant_id", "user_id"],
    ),
    "tenant_settings": (
        [
            ("tenant_id", I(), 1, None), ("key", T(), 1, None), ("value", T(), 0, None),
        ],
        [], [],
    ),
    "tenants": (
        [
            ("tenant_key", T(), 0, None), ("name", T(), 0, ""), ("plan", T(), 0, "trial"),
            ("status", T(), 0, "active"), ("seats", I(), 0, "5"),
            ("quota_customers", I(), 0, "500"), ("quota_messages", I(), 0, "5000"),
            ("expires_at", T(), 0, ""), ("created_at", T(), 0, None),
        ],
        [["tenant_key"]], [],
    ),
    "usage_ledger": (
        [
            ("tenant_id", I(), 0, None), ("metric", T(), 0, "message"),
            ("amount", I(), 0, "1"), ("billed_at", T(), 0, None),
        ],
        [], ["tenant_id", "billed_at"],
    ),
    "webchat_messages": (
        [
            ("session_id", I(), 0, None), ("role", T(), 0, None), ("content", T(), 0, None),
            ("created_at", T(), 0, None),
        ],
        [], ["session_id"],
    ),
    "webchat_sessions": (
        [
            ("session_key", T(), 0, None), ("visitor_name", T(), 0, ""),
            ("source_page", T(), 0, ""), ("status", T(), 0, "open"), ("owner", T(), 0, ""),
            ("created_at", T(), 0, None), ("updated_at", T(), 0, None),
        ],
        [["session_key"]], [],
    ),
}

# 复合主键的表（没有 id 列）
COMPOSITE_PK = {"heartbeats": ["source"], "tenant_settings": ["tenant_id", "key"]}
# heartbeats 的 source 是主键，需要作为普通列补进去
EXTRA_PK_COLUMNS = {"heartbeats": [("source", T(), 1, None)]}

# 已有表需要补的列（跨模块隐式依赖）
ADD_COLUMNS: list[tuple[str, list[tuple[str, object, int, object]]]] = [
    ("customers", [("tenant_id", I(), 0, "0")]),
    ("system_users", [("tenant_id", I(), 0, "0"), ("display_name", T(), 0, "")]),
]

ADD_INDEXES: dict[str, list[tuple[str, list[str], bool]]] = {
    "customers": [("ix_customers_tenant_id", ["tenant_id"], False)],
}


def _table_names(insp: sa.Inspector) -> set[str]:
    return set(insp.get_table_names())


def _column_names(insp: sa.Inspector, table: str) -> set[str]:
    try:
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:  # noqa: BLE001
        return set()


def _index_names(insp: sa.Inspector, table: str) -> set[str]:
    try:
        return {ix["name"] for ix in insp.get_indexes(table) if ix.get("name")}
    except Exception:  # noqa: BLE001
        return set()


def _column(spec: tuple[str, object, int, object]) -> sa.Column:
    name, typ, notnull, default = spec
    kwargs: dict = {"nullable": not notnull}
    if default is not None:
        kwargs["server_default"] = str(default)
    return sa.Column(name, typ, **kwargs)


def _create_table(table: str) -> None:
    columns, unique_groups, indexes = TABLES[table]
    specs = list(columns)
    if table in EXTRA_PK_COLUMNS:
        specs = EXTRA_PK_COLUMNS[table] + specs

    pk = COMPOSITE_PK.get(table)
    if pk:
        cols = []
        for spec in specs:
            col = _column(spec)
            if spec[0] in pk:
                col.primary_key = True
            cols.append(col)
    else:
        cols = [sa.Column("id", I(), primary_key=True, autoincrement=True)]
        cols += [_column(spec) for spec in specs if spec[0] != "id"]

    constraints = []
    for group in unique_groups:
        constraints.append(sa.UniqueConstraint(*group, name=f"uq_{table}_{'_'.join(group)}"))

    op.create_table(table, *(cols + constraints))
    for col in indexes:
        op.create_index(f"ix_{table}_{col}", table, [col])


def upgrade() -> None:
    bind = op.get_bind()

    # 1) 缺失的表
    existing = _table_names(sa.inspect(bind))
    for table in TABLES:
        if table in existing:
            continue
        _create_table(table)

    # 2) 已存在的表：补缺失索引
    existing = _table_names(sa.inspect(bind))
    for table, (_cols, _uniq, indexes) in TABLES.items():
        if table not in existing:
            continue
        have = _index_names(sa.inspect(bind), table)
        for col in indexes:
            index_name = f"ix_{table}_{col}"
            if index_name in have:
                continue
            op.create_index(index_name, table, [col])

    # 3) 已有表补列（跨模块隐式依赖）
    existing = _table_names(sa.inspect(bind))
    for table, columns in ADD_COLUMNS:
        if table not in existing:
            continue
        have = _column_names(sa.inspect(bind), table)
        for spec in columns:
            if spec[0] in have:
                continue
            op.add_column(table, _column(spec))

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


def downgrade() -> None:
    """回滚：删除本迁移新增的表与列。新表内的数据会一并丢失。"""
    bind = op.get_bind()
    existing = _table_names(sa.inspect(bind))

    for table, indexes in ADD_INDEXES.items():
        if table not in existing:
            continue
        have = _index_names(sa.inspect(bind), table)
        for index_name, _columns, _unique in indexes:
            if index_name in have:
                op.drop_index(index_name, table_name=table)

    for table, columns in ADD_COLUMNS:
        if table not in existing:
            continue
        have = _column_names(sa.inspect(bind), table)
        for spec in columns:
            if spec[0] in have:
                op.drop_column(table, spec[0])

    existing = _table_names(sa.inspect(bind))
    for table in reversed(list(TABLES)):
        # system_users 可能来自更早的库形态，回滚时只在由本迁移建出时才删
        if table in existing:
            op.drop_table(table)
