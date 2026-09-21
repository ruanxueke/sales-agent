#!/usr/bin/env bash
# 数据库结构升级入口 —— 发布流程必须调用本脚本，不要再依赖 init_db() 的 create_all。
#
# 背景：create_all 只建「缺失的表」，永远不会修改已存在的表。老的现网库是历史上
# 由 create_all 建出来的，没有 alembic_version 记录，直接 `alembic upgrade head`
# 会在 0001 就报「表已存在」。所以这类库必须先盖章（stamp）到迁移链末端，再由
# 0007 这类「幂等补齐」迁移把差异补上。
#
# 三种库形态必须区分开，判据如下：
#   1) 全新空库        -> 没有 alembic_version，也没有 customers 表 -> 正常 upgrade 全链
#   2) create_all 老库 -> 没有 alembic_version，但有 customers 表   -> 先 stamp 0006
#   3) 已纳管库        -> 有 alembic_version                        -> 增量 upgrade
# 第 3 步的结构校验会在任何不匹配时直接失败，避免把错的结构带上线。
#
# 幂等：可重复执行。
set -euo pipefail

cd "$(dirname "$0")/.."

PY="${PYTHON_BIN:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  PY=python
fi

echo "===== [1/3] 判定数据库形态 ====="
# 输出两个标记：version_table=yes/no、core_table=yes/no
STATE="$("$PY" - <<'PYEOF'
import os
import sys

sys.path.insert(0, os.getcwd())
from sqlalchemy import create_engine, inspect  # noqa: E402

url = os.getenv("DATABASE_URL") or "sqlite:///%s/data/customers.db" % os.getcwd()
try:
    names = set(inspect(create_engine(url)).get_table_names())
except Exception as exc:
    print("ERR=%s" % exc)
    raise SystemExit(0)

print("version_table=%s" % ("yes" if "alembic_version" in names else "no"))
print("core_table=%s" % ("yes" if "customers" in names else "no"))
print("table_count=%d" % len(names))
PYEOF
)"
echo "$STATE" | sed 's/^/   /'

case "$STATE" in
  ERR=*)
    echo "!! 无法连接数据库：${STATE#ERR=}"
    exit 1
    ;;
esac

HAS_VERSION="$(printf '%s\n' "$STATE" | sed -n 's/^version_table=//p')"
HAS_CORE="$(printf '%s\n' "$STATE" | sed -n 's/^core_table=//p')"

if [ "$HAS_VERSION" = "no" ] && [ "$HAS_CORE" = "yes" ]; then
  echo "   形态 2：create_all 建出的历史库 -> 先盖章到 0006_add_display_id"
  "$PY" -m alembic stamp 0006_add_display_id
elif [ "$HAS_VERSION" = "no" ]; then
  echo "   形态 1：全新空库 -> 直接执行完整迁移链"
else
  echo "   形态 3：已纳管库 -> 按当前版本增量升级"
fi

echo "===== [2/3] 执行 alembic upgrade head ====="
"$PY" -m alembic upgrade head

echo "===== [3/3] 校验结构一致性 ====="
"$PY" - <<'PYEOF'
"""升级后校验：库里实际结构与 ORM 元数据必须完全一致，否则发布直接失败。"""
import os
import sys

sys.path.insert(0, os.getcwd())
from sqlalchemy import create_engine, inspect  # noqa: E402

from core.db import Base  # noqa: E402
import core.models  # noqa: E402,F401

url = os.getenv("DATABASE_URL") or "sqlite:///%s/data/customers.db" % os.getcwd()
insp = inspect(create_engine(url))
have = set(insp.get_table_names()) - {"alembic_version"}
meta = set(Base.metadata.tables.keys())

missing_tables = sorted(meta - have)
gaps = {}
for table in sorted(meta & have):
    orm_cols = {c.name for c in Base.metadata.tables[table].columns}
    db_cols = {c["name"] for c in insp.get_columns(table)}
    miss = sorted(orm_cols - db_cols)
    if miss:
        gaps[table] = miss

print("   表数量: 库里 %d / ORM %d" % (len(have), len(meta)))
if missing_tables:
    print("!! 缺表: %s" % ", ".join(missing_tables))
if gaps:
    for table, cols in gaps.items():
        print("!! 缺字段 %s: %s" % (table, ", ".join(cols)))
if missing_tables or gaps:
    raise SystemExit("结构校验未通过，已中止发布")

print("   结构校验通过：库结构与 ORM 完全一致")
PYEOF

echo "===== 数据库结构升级完成 ====="
