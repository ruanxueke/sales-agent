from __future__ import annotations
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from core.db import Base  # noqa: E402
import core.models  # noqa: E402,F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# DATABASE_URL 优先；未设置时兜底到项目内的 SQLite。
# 注意：兜底路径基于 PROJECT_ROOT 而非 os.getcwd()——否则在别的目录执行 alembic
# 会静默连到另一个空库，从而把迁移打在错误的库上。
url = os.getenv("DATABASE_URL", f"sqlite:///{os.path.join(PROJECT_ROOT, 'data', 'customers.db')}")
config.set_main_option("sqlalchemy.url", url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        render_as_batch=url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite 不支持 ALTER COLUMN，必须走 batch 模式；
            # 否则 --autogenerate 产出的改列语句会在 SQLite 上静默失效。
            render_as_batch=url.startswith("sqlite"),
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
