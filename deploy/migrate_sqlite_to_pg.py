"""SQLite -> PostgreSQL 数据迁移：按列交集复制，保留 id 并同步序列"""
from __future__ import annotations
import sys

from sqlalchemy import create_engine, text

from config.settings import settings
import logging
logger = logging.getLogger(__name__)


SQLITE_PATH = "/app/data/customers.db"
PG_URL = settings.DATABASE_URL


def migrate():
    s_engine = create_engine(f"sqlite:///{SQLITE_PATH}")
    p_engine = create_engine(PG_URL)
    total = 0
    with s_engine.connect() as sconn, p_engine.connect() as pconn:
        tables = [r[0] for r in sconn.execute(text(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name"
        )).fetchall()]
        pg_tables = {r[0] for r in pconn.execute(text(
            "select table_name from information_schema.tables where table_schema='public'"
        )).fetchall()}
        for t in tables:
            try:
                pconn.rollback()
            except Exception as e:
                logger.warning("回滚失败: %s", e)
            if t not in pg_tables:
                print(f"skip-table {t}: not in postgres")
                continue
            try:
                s_cols = [r[1] for r in sconn.execute(text(f"PRAGMA table_info({t})")).fetchall()]
                p_cols = [r[0] for r in pconn.execute(text(
                    f"select column_name from information_schema.columns where table_name='{t}' and table_schema='public'"
                )).fetchall()]
            except Exception as e:
                print(f"skip-table {t}: {str(e)[:80]}")
                continue
            cols = [c for c in s_cols if c in p_cols]
            if not cols:
                continue
            try:
                rows = sconn.execute(text(f'select {",".join(cols)} from {t}')).fetchall()
            except Exception as e:
                print(f"skip-table {t}: {str(e)[:80]}")
                continue
            if not rows:
                print(f"{t}: 0")
                continue
            col_str = ",".join(cols)
            ph = ",".join([f":{c}" for c in cols])
            n = 0
            for row in rows:
                data = dict(zip(cols, row))
                try:
                    with pconn.begin_nested():
                        pconn.execute(text(f'insert into {t} ({col_str}) values ({ph})'), data)
                    n += 1
                except Exception:
                    # 单行失败（主键冲突/约束），跳过不中断
                    continue
            total += n
            try:
                with pconn.begin_nested():
                    pconn.execute(text(
                        f"select setval(pg_get_serial_sequence('{t}','id'), (select coalesce(max(id),1) from {t}))"
                    ))
            except Exception as e:
                logger.error("重置自增序列失败，后续插入可能主键冲突: %s", e)
            try:
                pconn.commit()
            except Exception:
                try:
                    pconn.rollback()
                except Exception as e:
                    logger.warning("回滚失败: %s", e)
            print(f"{t}: {n}")
        try:
            pconn.commit()
        except Exception:
            try:
                pconn.rollback()
            except Exception as e:
                logger.warning("回滚失败: %s", e)
    print(f"TOTAL: {total}")


if __name__ == "__main__":
    migrate()
