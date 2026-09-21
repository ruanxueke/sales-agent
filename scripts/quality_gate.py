"""质量门：结构检查 + 自测脚本回归 + 可选的 pytest。

一次跑完发布前必须过的东西，任何一项失败都以非 0 退出，可以直接挂到 CI 或
发布脚本里（fail fast）。刻意只依赖标准库，离线环境也能跑。

三项结构检查（对应检查清单 P2-13）：

1. **import 检查** —— 逐个导入所有一方模块，抓语法错误、导入期副作用炸掉、
   以及"某个文件只在被 import 时才暴露的 NameError"（本项目就出现过
   `logger` 未定义这类问题）。
2. **乱码检查** —— 扫 U+FFFD 替换字符，以及"整条字符串字面量只剩问号"的
   占位残留。注意不能简单找 `?`：SQL 占位符本身就是 `?`，误报会把门变成噪音。
3. **迁移检查** ——
   * 迁移链必须是**单头线性**（有分叉/断链时 `upgrade head` 行为不确定）；
   * 全新空库跑完 `upgrade head` 后，实际建出来的表/列必须与 ORM 元数据一致
     —— 这是当年「create_all 与 alembic 两套结构」的根因，必须在门口拦住；
   * `deploy/migrate.sh` 里 stamp 的 revision 必须真实存在（改名字会静默失败）。

用法：
    python scripts/quality_gate.py                # 全跑
    python scripts/quality_gate.py --only import  # 只跑某一项
    python scripts/quality_gate.py --skip-tests   # 跳过自测脚本回归
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

# 一方代码目录（静态检查的目标）
SOURCE_DIRS = ["api", "core", "config", "connectors", "knowledge", "utils", "wechat_bridge", "scripts", "deploy"]
SOURCE_FILES = ["api_server.py", "main.py", "fix_garbled_data.py", "sync_product_info.py"]

# 需要重依赖（桌面/OCR/浏览器）才能导入的模块，import 检查里放行
IMPORT_HEAVY = (
    "wechat_bridge.reader_adapter",
    "wechat_bridge.ui_sender",
    "wechat_bridge.notifier",
    "wechat_bridge.run",
    "wechat_bridge.daemon",
)

# 不参与静态扫描的路径片段
SKIP_PARTS = (
    "release", "desktop-client", "wechat-bot", "node_modules",
    "__pycache__", ".git", "vendor", "dist",
)

SCRIPT_TESTS = [
    "tests/test_backup.py",
    "tests/test_business_modules.py",
    "tests/test_concurrency.py",
    "tests/test_enterprise.py",
    "tests/test_leads.py",
    "tests/test_message_splitter.py",
    "tests/test_personal_wechat.py",
    "tests/test_self_check.py",
    "tests/test_solda_modules.py",
    "tests/test_tenant_isolation.py",
    "tests/test_commercial_hardening.py",
]


class Gate:
    def __init__(self):
        self.failures = []
        self.checks = 0

    def ok(self, label, detail=""):
        self.checks += 1
        print("  [PASS] %s%s" % (label, (" -> " + str(detail)) if detail else ""))

    def fail(self, label, detail=""):
        self.checks += 1
        self.failures.append(label)
        print("  [FAIL] %s%s" % (label, (" -> " + str(detail)) if detail else ""))

    def expect(self, cond, label, detail=""):
        (self.ok if cond else self.fail)(label, detail)
        return bool(cond)


def _iter_source_files():
    for d in SOURCE_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            if any(part in SKIP_PARTS for part in p.parts):
                continue
            yield p
    for f in SOURCE_FILES:
        p = ROOT / f
        if p.is_file():
            yield p


def _module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    return ".".join(rel.parts)


def check_imports(gate: Gate) -> None:
    print("\n=== 1) import 检查 ===", flush=True)
    mods = []
    for p in sorted(_iter_source_files()):
        name = _module_name(p)
        if any(name == h or name.startswith(h + ".") for h in IMPORT_HEAVY):
            continue
        if name.endswith(".__init__"):
            name = name[: -len(".__init__")]
        mods.append(name)

    gate.expect(len(mods) > 30, "待导入模块数量合理", len(mods))

    # 分批 + 每批独立子进程：
    #   * 一个模块在导入期阻塞（等网络、起线程、连向量库）不会把整轮拖死；
    #   * 每批带超时，超时只看得到"这批没回来"，所以批内再逐模块回显进度；
    #   * 比"每个模块起一个子进程"快得多（182 次解释器启动开销省掉了）。
    BATCH = 20
    results = {}
    timed_out = []
    with tempfile.TemporaryDirectory() as tmp:
        env = {
            **os.environ,
            "DATABASE_URL": "sqlite:///" + os.path.join(tmp, "import_check.db"),
            "AUTO_CREATE_TABLES": "false",
            "ENABLE_API_DOCS": "false",
            "REDIS_URL": "",
            "CACHE_REDIS_URL": "",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "WECHAT_BRIDGE_HOME": tmp,
        }
        runner = (
            "import importlib, json, sys\n"
            "mods = json.loads(sys.argv[1])\n"
            "failed = []\n"
            "for m in mods:\n"
            "    print('<<<TRY>>>' + m, flush=True)\n"
            "    try:\n"
            "        importlib.import_module(m)\n"
            "    except BaseException as e:\n"
            "        failed.append([m, type(e).__name__, str(e).replace(chr(10), ' ')[:200]])\n"
            "        print('<<<ERR>>>' + m, flush=True)\n"
            "print('<<<RESULT>>>' + json.dumps(failed, ensure_ascii=False), flush=True)\n"
        )
        batches = [mods[i:i + BATCH] for i in range(0, len(mods), BATCH)]
        for bi, batch in enumerate(batches, 1):
            print("        批次 %d/%d (%d 个模块)" % (bi, len(batches), len(batch)), flush=True)
            try:
                r = subprocess.run(
                    [PY, "-u", "-c", runner, json.dumps(batch)],
                    cwd=str(ROOT), env=env, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=180,
                )
                out = r.stdout or ""
            except subprocess.TimeoutExpired as e:
                out = (e.stdout or "") if isinstance(e.stdout, str) else (e.stdout or b"").decode("utf-8", "replace")
                tried = [l[len("<<<TRY>>>"):] for l in out.splitlines() if l.startswith("<<<TRY>>>")]
                done_err = [l[len("<<<ERR>>>"):] for l in out.splitlines() if l.startswith("<<<ERR>>>")]
                stuck = [m for m in tried if m not in done_err]
                stuck = stuck[-1:] if stuck else ["<未知>"]
                timed_out.extend(stuck)
                print("        本批超时，卡在: %s" % stuck, flush=True)
                continue
            payload = None
            for line in out.splitlines():
                if line.startswith("<<<RESULT>>>"):
                    try:
                        payload = json.loads(line[len("<<<RESULT>>>"):])
                    except Exception:
                        payload = None
            if payload is None:
                results["<runner>"] = ("RunnerCrash", (r.stderr or "").strip()[-300:])
            else:
                for name, kind, msg in payload:
                    results[name] = (kind, msg)

    failed = sorted(set(list(results) + timed_out))
    gate.expect(not failed, "全部 %d 个模块可导入" % len(mods), "失败 %d 个" % len(failed))

    # 失败/超时的模块逐个隔离复现，拿到真正的首行原因
    if failed:
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                **os.environ,
                "DATABASE_URL": "sqlite:///" + os.path.join(tmp, "iso.db"),
                "AUTO_CREATE_TABLES": "false",
                "REDIS_URL": "",
                "CACHE_REDIS_URL": "",
                "PYTHONDONTWRITEBYTECODE": "1",
                "WECHAT_BRIDGE_HOME": tmp,
            }
            for name in failed[:20]:
                if name == "<runner>":
                    print("        - <runner>: %s" % (results.get(name, ("", ""))[1],), flush=True)
                    continue
                try:
                    rr = subprocess.run(
                        [PY, "-u", "-c", "import %s" % name],
                        cwd=str(ROOT), env=env, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=60,
                    )
                    tail = [x for x in (rr.stderr or "").strip().splitlines() if x.strip()]
                    detail = tail[-1][:160] if tail else "exit=%s" % rr.returncode
                except subprocess.TimeoutExpired:
                    detail = "导入期阻塞（单模块 60s 未返回）"
                print("        - %s: %s" % (name, detail), flush=True)


# SQL 占位符本身就是 ?，所以不能直接找问号；这里只抓"整条字符串字面量
# 除问号外没有别的内容"的情况——那是中文被替换成 ? 之后的典型残留。
_PLACEHOLDER_STR = re.compile(r"""(['"])((?:\s*\?\s*){3,})\1""")
_STRING_LITERAL = re.compile(r"""(['"])((?:\\.|(?!\1)[^\\])*)\1""")


def check_mojibake(gate: Gate) -> None:
    print("\n=== 2) 乱码检查 ===", flush=True)
    exts = {".py", ".js", ".html", ".css", ".md", ".json", ".bat", ".sh", ".txt"}
    scanned = 0
    bad_fffd = []
    bad_placeholder = []

    targets = []
    for d in SOURCE_DIRS + ["static", "tests"]:
        base = ROOT / d
        if base.is_dir():
            for p in base.rglob("*"):
                if p.is_file() and p.suffix.lower() in exts and not any(x in SKIP_PARTS for x in p.parts):
                    targets.append(p)
    for f in SOURCE_FILES + ["Dockerfile", "docker-compose.yml", "deploy.sh", "README.md"]:
        p = ROOT / f
        if p.is_file():
            targets.append(p)

    for p in sorted(set(targets)):
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            bad_fffd.append((str(p.relative_to(ROOT)), "非法 UTF-8 编码"))
            continue
        scanned += 1
        rel = str(p.relative_to(ROOT))
        if "\ufffd" in text:
            n = text.count("\ufffd")
            bad_fffd.append((rel, "U+FFFD x%d" % n))
        if p.suffix.lower() in {".py", ".js"}:
            for m in _PLACEHOLDER_STR.finditer(text):
                line = text[: m.start()].count("\n") + 1
                bad_placeholder.append((rel, "L%d %s" % (line, m.group(2))))

    gate.expect(scanned > 50, "扫描文件数量合理", scanned)
    gate.expect(not bad_fffd, "没有 U+FFFD 替换字符 / 非法编码", bad_fffd[:10])
    gate.expect(not bad_placeholder, "没有「只剩问号」的占位残留", bad_placeholder[:10])
    for item in (bad_fffd + bad_placeholder)[:15]:
        print("        - %s: %s" % item)


def _read_migrations():
    d = ROOT / "migrations" / "versions"
    revs = {}
    for p in sorted(d.glob("*.py")):
        if p.name.startswith("__"):
            continue
        s = p.read_text(encoding="utf-8")
        r = re.search(r"^revision\s*=\s*['\"]([^'\"]+)", s, re.M)
        dr = re.search(r"^down_revision\s*=\s*(.+)$", s, re.M)
        if not r:
            continue
        down = None
        if dr:
            raw = dr.group(1).strip()
            if raw not in ("None", "none"):
                found = re.findall(r"['\"]([^'\"]+)['\"]", raw)
                # down_revision 可以是元组（合并点），这里保留列表以检出分叉
                down = found if len(found) > 1 else (found[0] if found else raw.strip("'\""))
        revs[r.group(1)] = {"file": p.name, "down": down}
    return revs


def check_migrations(gate: Gate) -> None:
    print("\n=== 3) 迁移检查 ===", flush=True)
    print("        校验迁移链...", flush=True)
    revs = _read_migrations()
    gate.expect(len(revs) >= 8, "识别到迁移版本数量合理", len(revs))

    downs = [v["down"] for v in revs.values()]
    multi = [k for k, v in revs.items() if isinstance(v["down"], list) and len(v["down"]) > 1]
    gate.expect(not multi, "没有合并点（多父迁移）", multi)

    children = {}
    for rev, info in revs.items():
        down = info["down"]
        if isinstance(down, list):
            continue
        if down is None:
            continue
        children.setdefault(down, []).append(rev)
        if down not in revs:
            gate.fail("迁移 %s 的 down_revision 指向不存在的版本" % rev, down)

    heads = [r for r in revs if r not in children]
    gate.expect(len(heads) == 1, "迁移链是单头（head 唯一）", heads)

    # deploy/migrate.sh 里 stamp 的 revision 必须真实存在
    migrate_sh = ROOT / "deploy" / "migrate.sh"
    if migrate_sh.is_file():
        sh = migrate_sh.read_text(encoding="utf-8")
        stamped = set(re.findall(r"alembic stamp\s+([A-Za-z0-9_]+)", sh))
        missing = sorted(x for x in stamped if x not in revs)
        gate.expect(bool(stamped), "migrate.sh 里有 stamp 步骤", sorted(stamped))
        gate.expect(not missing, "stamp 的 revision 都真实存在", missing)

    # 真正有杀伤力的那条：全新空库跑完 upgrade head 后，表/列必须与 ORM 一致。
    print("        读取 ORM 元数据...", flush=True)
    from_orm = _orm_schema()
    print("        在全新空库上执行 alembic upgrade head...（较慢）", flush=True)
    applied = _applied_schema()
    if from_orm is None or applied is None:
        gate.fail("能取到 ORM 元数据与迁移后结构（跳过深度比对）",
                  "orm=%s applied=%s" % (from_orm is not None, applied is not None))
        return

    missing_tables = sorted(set(from_orm) - set(applied))
    gate.expect(not missing_tables, "迁移链能建出 ORM 里全部表（含新增表）",
                "缺 %d 张: %s" % (len(missing_tables), missing_tables[:8]))

    gaps = []
    for table, cols in from_orm.items():
        if table not in applied:
            continue
        # applied 是从子进程 JSON 回来的，列是 list 不是 set；这里必须显式转换。
        miss = sorted(set(cols) - set(applied[table]))
        if miss:
            gaps.append("%s: %s" % (table, miss))
    gate.expect(not gaps, "迁移链能建出 ORM 里全部列（含新增字段）",
                "缺 %d 处: %s" % (len(gaps), gaps[:6]))


def _orm_schema():
    """用独立子进程取 ORM 元数据，避免污染当前进程。"""
    code = (
        "import json,sys;sys.path.insert(0,'.');"
        "import core.models as m;"
        "print(json.dumps({t.name: sorted(c.name for c in t.columns) "
        "for t in m.Base.metadata.sorted_tables}))"
    )
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "DATABASE_URL": "sqlite:///" + os.path.join(tmp, "orm.db"),
               "AUTO_CREATE_TABLES": "false", "REDIS_URL": ""}
        r = subprocess.run(
            [PY, "-c", code], cwd=str(ROOT), env=env, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=180,
        )
        if r.returncode != 0:
            print("        ORM 元数据读取失败:", (r.stderr or "").strip()[-300:])
            return None
        import json
        try:
            return json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            return None


def _applied_schema():
    """在全新空库上跑 alembic upgrade head，反射出真实结构。"""
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "fresh.db")
        env = {
            **os.environ,
            "DATABASE_URL": "sqlite:///" + db,
            "AUTO_CREATE_TABLES": "false",
            "REDIS_URL": "",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        r = subprocess.run(
            [PY, "-m", "alembic", "upgrade", "head"],
            cwd=str(ROOT), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=600,
        )
        if r.returncode != 0:
            print("        alembic upgrade head 失败:", (r.stderr or "").strip()[-400:])
            return None
        code = (
            "import json,sys;from sqlalchemy import create_engine,inspect;"
            "e=create_engine(sys.argv[1]);i=inspect(e);"
            "print(json.dumps({t: sorted(c['name'] for c in i.get_columns(t)) "
            "for t in i.get_table_names()}))"
        )
        r2 = subprocess.run(
            [PY, "-c", code, "sqlite:///" + db], cwd=str(ROOT), env=env,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=180,
        )
        if r2.returncode != 0:
            print("        结构反射失败:", (r2.stderr or "").strip()[-300:])
            return None
        import json
        try:
            return json.loads(r2.stdout.strip().splitlines()[-1])
        except Exception:
            return None


def check_script_tests(gate: Gate) -> None:
    print("\n=== 4) 自测脚本回归 ===")
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, rel in enumerate(SCRIPT_TESTS):
            path = ROOT / rel
            if not path.is_file():
                rows.append((rel, 127, "文件不存在"))
                continue
            env = {
                **os.environ,
                "DATABASE_URL": "sqlite:///" + os.path.join(tmp, "reg_%02d.db" % i),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONIOENCODING": "utf-8",
                "REDIS_URL": "",
                "CACHE_REDIS_URL": "",
                "WECHAT_BRIDGE_HOME": os.path.join(tmp, "bridge_%02d" % i),
            }
            r = subprocess.run(
                [PY, rel], cwd=str(ROOT), env=env, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=600,
            )
            tail = [x for x in (r.stdout or "").strip().splitlines() if x.strip()]
            msg = tail[-1][:80] if tail else ((r.stderr or "").strip().splitlines() or [""])[-1][:80]
            rows.append((rel, r.returncode, msg))

    for rel, code, msg in rows:
        print("        %-34s exit=%-4s %s" % (rel, code, msg), flush=True)
    failed = [r for r in rows if r[1] != 0]
    gate.expect(not failed, "自测脚本全部通过（%d 个）" % len(rows),
                "失败: %s" % [r[0] for r in failed])


def check_pytest(gate: Gate) -> None:
    print("\n=== 5) pytest（可选） ===", flush=True)
    r = subprocess.run(
        [PY, "-m", "pytest", "--version"], cwd=str(ROOT),
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=60,
    )
    if r.returncode != 0:
        print("        未安装 pytest，跳过（pip install -r requirements-dev.txt）")
        return
    with tempfile.TemporaryDirectory() as tmp:
        env = {
            **os.environ,
            "DATABASE_URL": "sqlite:///" + os.path.join(tmp, "pytest.db"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "REDIS_URL": "",
            "CACHE_REDIS_URL": "",
        }
        r = subprocess.run(
            [PY, "-m", "pytest", "-q"], cwd=str(ROOT), env=env,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=900,
        )
    tail = [x for x in (r.stdout or "").strip().splitlines() if x.strip()]
    print("        " + (tail[-1] if tail else ""))
    gate.expect(r.returncode in (0, 5), "pytest 无失败用例（5=没收集到用例）", r.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="发布前质量门")
    parser.add_argument("--only", default="", help="只跑某一项: import|mojibake|migrations|tests|pytest")
    parser.add_argument("--skip-tests", action="store_true", help="跳过自测脚本回归")
    parser.add_argument("--skip-pytest", action="store_true", help="跳过 pytest")
    args = parser.parse_args()

    gate = Gate()
    print("质量门开始 root=%s python=%s" % (ROOT, PY))

    plan = {
        "import": lambda: check_imports(gate),
        "mojibake": lambda: check_mojibake(gate),
        "migrations": lambda: check_migrations(gate),
        "tests": lambda: check_script_tests(gate),
        "pytest": lambda: check_pytest(gate),
    }
    if args.only:
        if args.only not in plan:
            print("未知检查项: %s（可选：%s）" % (args.only, ",".join(plan)))
            return 2
        plan[args.only]()
    else:
        check_imports(gate)
        check_mojibake(gate)
        check_migrations(gate)
        if not args.skip_tests:
            check_script_tests(gate)
        if not args.skip_pytest:
            check_pytest(gate)

    print("\n" + "=" * 60)
    if gate.failures:
        print("质量门未通过：%d/%d 项失败" % (len(gate.failures), gate.checks))
        for f in gate.failures:
            print("  - %s" % f)
        return 1
    print("质量门通过：%d 项检查全部通过" % gate.checks)
    return 0


if __name__ == "__main__":
    sys.exit(main())
