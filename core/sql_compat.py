"""sqlite3 兼容连接层 —— 把历史模块的直连 SQL 落到「与 ORM 同一个库」。

为什么要这一层
--------------
项目里有 30 多个模块用 `sqlite3.connect(DATA_DIR/"customers.db")` 直连 SQL，
而生产环境的 ORM 走的是 `DATABASE_URL`（PostgreSQL）。两者**不是同一个库**，
后果（详见 docs/全项目检查与优化清单-20260911.md 的 A5）：

1. 这些模块去 SQLite 找 `orders` / `leads` / `approval_flows` 等**只存在于 PG** 的表
   -> 要么 `no such table`，要么读到上云前的陈旧数据（业绩榜/佣金永远是老数字）；
2. 登录态、成员、配额、审批、SLA 全被写进 SQLite，与业务数据割裂，且**绝不在 PG**；
3. api / official / worker / beat 四个容器共享同一个 SQLite 文件并发写
   -> `database is locked`（代码里没有任何重试包装）。

本模块提供与 `sqlite3` 同名同形的 `connect()`，把连接重定向到 `DATABASE_URL`，
因此各模块**只需把 `import sqlite3` 换成 `from core import sql_compat as sqlite3`**，
调用点一行都不用改。

行为约定
--------
- **参数占位符**：支持 `?`（自动转成 SQLAlchemy 具名参数），SQLite 与 PG 通用。
- **行对象**：始终返回 `Row`，同时支持 `row[0]`、`row["col"]`、`dict(row)`、`.keys()`，
  是 `sqlite3.Row` 的超集。
- **DDL**：`CREATE` / `ALTER` / `DROP` / `executescript` **只在后端是 SQLite 时执行**。
  在 PG 上直接跳过 —— 因为 PG 的表结构由 alembic 迁移负责（见 migrations/versions/0008_*），
  再让各模块自己建表就会和迁移链打架。跳过时会打 debug 日志，不是静默丢弃。
- **PRAGMA table_info(x)** / `sqlite_master` 查询：用 SQLAlchemy inspection 重写，
  两种方言都能返回正确结果（这些结果被用于"列是否存在"的判断和动态 SELECT）。
- **异常**：`IntegrityError` / `OperationalError` 直接复用 SQLAlchemy 的同名异常，
  所以 `except sqlite3.IntegrityError:` 这类捕获语义不变。
- **`lastrowid`**：通过 `RETURNING <主键>` 取得，SQLite(>=3.35) 与 PG 都支持。

注意：`wechat_bridge/` 下的模块**必须继续用真正的 sqlite3**（它们读的是微信本地库），
不要改成引用本模块。
"""
from __future__ import annotations

import logging
import re
import threading
from typing import Any, Iterable, Iterator, Optional, Sequence

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from config.settings import settings

logger = logging.getLogger(__name__)

__all__ = [
    "Row",
    "Error",
    "IntegrityError",
    "OperationalError",
    "Connection",
    "Cursor",
    "connect",
]

Error = SQLAlchemyError

# SQLite 与 PG 都不支持的 sqlite3 模块级常量，给个空实现，避免 import 期报错
PARSE_DECLTYPES = 1
PARSE_COLNAMES = 2

_DDL_PREFIX = re.compile(r"^\s*(CREATE|ALTER|DROP)\b", re.I)
_PRAGMA_TABLE_INFO = re.compile(r"^\s*PRAGMA\s+table_info\s*\(\s*([\w\"'\[\]]+)\s*\)\s*;?\s*$", re.I)
_SQLITE_MASTER_TABLES = re.compile(r"^\s*SELECT\s+name\s+FROM\s+sqlite_master\s+WHERE\s+type\s*=\s*'table'\s*;?\s*$", re.I)
_INSERT_PREFIX = re.compile(r"^\s*INSERT\s+INTO\s+([\w\"'\[\].]+)", re.I)
_HAS_RETURNING = re.compile(r"\bRETURNING\b", re.I)


class Row:
    """`sqlite3.Row` 的兼容实现：既可按序号取，也可按列名取。"""

    __slots__ = ("_keys", "_values", "_index")

    def __init__(self, keys: Sequence[str], values: Sequence[Any]):
        self._keys = tuple(keys)
        self._values = tuple(values)
        self._index = {k: i for i, k in enumerate(self._keys)}

    def keys(self) -> list[str]:
        return list(self._keys)

    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return self._values[key]
        try:
            return self._values[self._index[key]]
        except KeyError as exc:  # 与 sqlite3.Row 一致：找不到列名直接报错
            raise IndexError(f"no such column: {key}") from exc

    def get(self, key, default=None):
        idx = self._index.get(key)
        return default if idx is None else self._values[idx]

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __contains__(self, key) -> bool:
        return key in self._index

    def __eq__(self, other) -> bool:
        if isinstance(other, Row):
            return self._keys == other._keys and self._values == other._values
        return self._values == other

    def __repr__(self) -> str:
        return "<Row %s>" % ", ".join(
            "%s=%r" % (k, v) for k, v in zip(self._keys, self._values)
        )


def _to_row(keys: Sequence[str], values: Sequence[Any]) -> Row:
    return Row(keys, values)


def _translate_placeholders(sql: str) -> tuple[str, list[str]]:
    """把 `?` 占位符转成 SQLAlchemy 具名参数 `:p1, :p2...`。

    必须跳过字符串字面量和注释里的 `?`，否则会把 SQL 里的问号也当成占位符。
    """
    out: list[str] = []
    names: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        # 单引号字符串
        if ch == "'":
            out.append(ch)
            i += 1
            while i < n:
                out.append(sql[i])
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":  # 转义的单引号
                        out.append(sql[i + 1])
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        # 双引号标识符
        if ch == '"':
            out.append(ch)
            i += 1
            while i < n:
                out.append(sql[i])
                if sql[i] == '"':
                    i += 1
                    break
                i += 1
            continue
        # 行注释
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] != "\n":
                out.append(sql[i])
                i += 1
            continue
        # 块注释
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            out.append("/*")
            i += 2
            while i < n and not (sql[i] == "*" and i + 1 < n and sql[i + 1] == "/"):
                out.append(sql[i])
                i += 1
            out.append("*/")
            i = min(i + 2, n)
            continue
        if ch == "?":
            name = "p%d" % (len(names) + 1)
            names.append(name)
            out.append(":" + name)
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out), names


def _split_script(script: str) -> list[str]:
    """按分号切分 SQL 脚本（跳过字符串字面量里的分号）。"""
    stmts: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(script)
    while i < n:
        ch = script[i]
        if ch == "'":
            buf.append(ch)
            i += 1
            while i < n:
                buf.append(script[i])
                if script[i] == "'":
                    if i + 1 < n and script[i + 1] == "'":
                        buf.append(script[i + 1])
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


class Cursor:
    """`sqlite3.Cursor` 的最小兼容子集。"""

    def __init__(self, keys: Sequence[str] | None = None, rows: Sequence[Sequence[Any]] | None = None,
                 rowcount: int = -1, lastrowid: Optional[int] = None):
        self._keys = list(keys or [])
        self._rows = [list(r) for r in (rows or [])]
        self._pos = 0
        self._lastrowid = lastrowid
        self.description = tuple((k, None, None, None, None, None, None) for k in self._keys)
        self.rowcount = rowcount
        self.arraysize = 1

    @property
    def lastrowid(self) -> Optional[int]:
        return self._lastrowid

    def _next(self):
        if self._pos >= len(self._rows):
            return None
        row = self._rows[self._pos]
        self._pos += 1
        return _to_row(self._keys, row) if self._keys else tuple(row)

    def fetchone(self):
        return self._next()

    def fetchmany(self, size: int | None = None):
        size = size or self.arraysize
        out = []
        for _ in range(size):
            row = self._next()
            if row is None:
                break
            out.append(row)
        return out

    def fetchall(self):
        out = []
        while True:
            row = self._next()
            if row is None:
                break
            out.append(row)
        return out

    def __iter__(self):
        while True:
            row = self._next()
            if row is None:
                return
            yield row

    def close(self):
        self._rows = []
        self._pos = 0

    def execute(self, sql, params=()):  # 便于链式调用
        raise NotImplementedError("请通过 Connection.execute 使用")


class Connection:
    """把 `sqlite3.Connection` 的调用面映射到 SQLAlchemy 连接上。

    关键点：**始终只用一条底层连接 + 一把可重入锁**，从而完整保留历史代码
    「多次 execute 后一次 commit」的事务语义，同时消除 `check_same_thread=False`
    下的并发写隐患（今天多容器/多线程共享 SQLite 连接会 `database is locked`）。
    """

    def __init__(self, database: Any = None, **_kwargs):
        self._requested = str(database) if database else ""
        self._lock = threading.RLock()
        self._closed = False
        self._url = settings.DATABASE_URL or f"sqlite:///{settings.DATA_DIR / 'customers.db'}"
        self._dialect = "sqlite" if self._url.startswith("sqlite") else "other"
        # 每进程一个引擎，避免各模块各建连接池
        self._engine = _shared_engine(self._url)
        self._conn = self._engine.connect()
        self._pk_cache: dict[str, tuple[str, ...]] = {}
        self._is_sqlite = self._dialect == "sqlite"
        if self._requested and _normalize(self._requested) not in self._url:
            logger.debug(
                "sql_compat: 忽略模块自报的库路径 %s，统一使用 DATABASE_URL（%s）",
                self._requested, _mask(self._url),
            )

    # ---------- 内部 ----------

    def _pk_columns(self, table: str) -> tuple[str, ...]:
        table = table.strip('"').strip("'").strip("[]")
        if "." in table:
            table = table.split(".")[-1]
        if table in self._pk_cache:
            return self._pk_cache[table]
        try:
            pk = inspect(self._engine).get_pk_constraint(table)
            cols = tuple(pk.get("constrained_columns") or ())
        except Exception:  # noqa: BLE001 - 表不存在等情况
            cols = ()
        self._pk_cache[table] = cols
        return cols

    def _read(self, sql: str, params) -> Cursor:
        result = self._conn.execute(text(sql), _bind(params) if not isinstance(params, dict) else params)
        keys = list(result.keys())
        rows = result.fetchall()
        return Cursor(keys=keys, rows=rows, rowcount=len(rows))

    def _handle_meta(self, sql: str) -> Optional[Cursor]:
        """把 SQLite 专有的元数据查询改写成方言无关的实现。"""
        m = _PRAGMA_TABLE_INFO.match(sql)
        if m:
            table = m.group(1).strip('"').strip("'").strip("[]")
            cols = []
            try:
                for i, col in enumerate(inspect(self._engine).get_columns(table)):
                    cols.append([i, col["name"], str(col.get("type")), 0 if col.get("nullable", True) else 1, None, 0])
            except Exception:  # noqa: BLE001 - 表不存在时返回空集，与 SQLite 行为一致
                cols = []
            return Cursor(keys=("cid", "name", "type", "notnull", "dflt_value", "pk"), rows=cols, rowcount=len(cols))

        if _SQLITE_MASTER_TABLES.match(sql):
            try:
                names = sorted(inspect(self._engine).get_table_names())
            except Exception:  # noqa: BLE001
                names = []
            return Cursor(keys=("name",), rows=[[n] for n in names], rowcount=len(names))
        return None

    def _ddl_skipped(self, sql: str) -> bool:
        return bool(_DDL_PREFIX.match(sql)) and not self._is_sqlite

    def _insert_with_returning(self, sql: str) -> str:
        """给 INSERT 补上 `RETURNING <主键>`，以便拿到 lastrowid。"""
        m = _INSERT_PREFIX.match(sql)
        if not m or _HAS_RETURNING.search(sql):
            return sql
        pks = self._pk_columns(m.group(1))
        if len(pks) != 1:
            return sql
        return sql.rstrip().rstrip(";") + " RETURNING " + pks[0]

    # ---------- sqlite3.Connection 的调用面 ----------

    @property
    def row_factory(self):
        return Row

    @row_factory.setter
    def row_factory(self, _value):
        # 本层恒定返回 Row（sqlite3.Row 的超集），无需切换
        return

    def execute(self, sql: str, params: Iterable[Any] | dict = ()):
        with self._lock:
            sql = (sql or "").strip()
            if not sql:
                return Cursor()

            if self._ddl_skipped(sql):
                logger.debug("sql_compat: 非 SQLite 后端，跳过 DDL（结构由 alembic 管理）: %s", sql[:80])
                return Cursor(rowcount=0)

            meta = self._handle_meta(sql)
            if meta is not None:
                return meta

            is_insert = bool(_INSERT_PREFIX.match(sql))
            if is_insert and not isinstance(params, dict):
                sql = self._insert_with_returning(sql)

            translated, names = _translate_placeholders(sql)
            if isinstance(params, dict):
                bound = params
            else:
                values = tuple(params or ())
                bound = dict(zip(names, values))
                if len(values) < len(names):
                    raise OperationalError(
                        "statement", dict(bound), Exception(
                            "参数个数不足：SQL 需要 %d 个，实际给了 %d 个" % (len(names), len(values))
                        ),
                    )
                if len(values) > len(names):
                    raise OperationalError(
                        "statement", dict(bound), Exception(
                            "参数个数过多：SQL 需要 %d 个，实际给了 %d 个" % (len(names), len(values))
                        ),
                    )

            result = self._conn.execute(text(translated), bound)
            lastrowid = None
            if result.returns_rows:
                keys = list(result.keys())
                rows = result.fetchall()
                if is_insert and len(keys) == 1:
                    # 这是 RETURNING 出来的主键，不当成结果集返回（与 sqlite3 的 INSERT 语义一致）
                    lastrowid = rows[0][0] if rows else None
                    return Cursor(rowcount=len(rows), lastrowid=lastrowid)
                return Cursor(keys=keys, rows=rows, rowcount=len(rows))

            rowcount = result.rowcount if result.rowcount is not None and result.rowcount >= 0 else 0
            if is_insert:
                try:
                    lastrowid = result.lastrowid
                except Exception:  # noqa: BLE001 - 某些方言/语句没有 lastrowid
                    lastrowid = None
            return Cursor(rowcount=rowcount, lastrowid=lastrowid)

    def executemany(self, sql: str, seq_of_params: Iterable[Iterable[Any]]):
        with self._lock:
            sql = (sql or "").strip()
            if self._ddl_skipped(sql):
                return Cursor(rowcount=0)
            translated, names = _translate_placeholders(sql)
            batch = [dict(zip(names, tuple(p or ()))) for p in seq_of_params]
            if not batch:
                return Cursor(rowcount=0)
            result = self._conn.execute(text(translated), batch)
            rowcount = result.rowcount if result.rowcount is not None and result.rowcount >= 0 else len(batch)
            return Cursor(rowcount=rowcount)

    def executescript(self, script: str):
        """执行多语句脚本。非 SQLite 后端直接跳过（结构由 alembic 管理）。"""
        with self._lock:
            if not self._is_sqlite:
                logger.debug(
                    "sql_compat: 非 SQLite 后端，跳过 executescript（%d 条语句，结构由 alembic 管理）",
                    len(_split_script(script or "")),
                )
                return Cursor(rowcount=0)
            count = 0
            for stmt in _split_script(script or ""):
                self._conn.execute(text(stmt))
                count += 1
            return Cursor(rowcount=count)

    def cursor(self) -> Cursor:
        return Cursor()

    def commit(self):
        with self._lock:
            self._conn.commit()

    def rollback(self):
        with self._lock:
            self._conn.rollback()

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._conn.commit()
            except Exception:  # noqa: BLE001 - 关闭前尽力提交，失败不掩盖原异常
                logger.debug("sql_compat: 关闭前提交失败，已忽略", exc_info=True)
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                logger.debug("sql_compat: 关闭连接失败，已忽略", exc_info=True)

    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()
        return False


# ============================================================
# 引擎复用
# ============================================================

_engine_lock = threading.Lock()
_engines: dict[str, Any] = {}


def _shared_engine(url: str):
    """同进程内按 URL 复用引擎，避免每个模块各建一个连接池。"""
    engine = _engines.get(url)
    if engine is not None:
        return engine
    with _engine_lock:
        engine = _engines.get(url)
        if engine is None:
            kwargs: dict = {"echo": False, "pool_pre_ping": True}
            if url.startswith("sqlite"):
                kwargs["connect_args"] = {"check_same_thread": False}
            else:
                # 历史模块中有多个导入期单例会长期持有连接。
                # 池容量必须覆盖这些单例，不能沿用 sqlite3 时代的 5+5。
                kwargs["pool_size"] = max(
                    20,
                    int(getattr(settings, "DB_POOL_SIZE", 20) or 20),
                )
                kwargs["max_overflow"] = max(
                    10,
                    int(getattr(settings, "DB_MAX_OVERFLOW", 10) or 10),
                )
                kwargs["pool_recycle"] = 3600
                kwargs["pool_timeout"] = 60
            engine = create_engine(url, **kwargs)
            _engines[url] = engine
        return engine


def _normalize(path: str) -> str:
    return path.replace("\\", "/").rstrip("/")


def _mask(url: str) -> str:
    """脱敏连接串里的口令，避免日志泄漏。"""
    return re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:***@", url)


def _bind(params) -> dict:
    return params if isinstance(params, dict) else {}


def connect(database: Any = None, *args, **kwargs) -> Connection:
    """与 `sqlite3.connect` 同形；`database` 仅用于日志，实际统一走 `DATABASE_URL`。"""
    return Connection(database, *args, **kwargs)
