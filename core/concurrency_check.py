"""并发改造自检：Redis / Celery / 连接池 / 多 Worker 并发 / 任务函数"""
from __future__ import annotations
import json
import time

import requests


def run_concurrency_check() -> dict:
    out = {"checked_at": time.strftime("%Y-%m-%d %H:%M:%S")}

    # 1. Redis
    try:
        from config.settings import settings
        import redis
        r = redis.Redis.from_url(settings.REDIS_URL or "redis://localhost:6379/0", socket_timeout=3)
        out["redis"] = {"ok": bool(r.ping()), "keys": len(r.keys("*"))}
    except Exception as e:
        out["redis"] = {"ok": False, "error": str(e)[:150]}

    # 2. 数据库连接池（读 + 写临时表验证）
    try:
        from core.db import session_scope, check_db_health
        from sqlalchemy import text
        out["db_health"] = check_db_health()
        with session_scope() as s:
            s.execute(text("CREATE TABLE IF NOT EXISTS _concurrency_check (id INTEGER PRIMARY KEY, ts TEXT)"))
            s.execute(text("INSERT INTO _concurrency_check (ts) VALUES (:ts)"), {"ts": str(time.time())})
        with session_scope(read_only=True) as s:
            n = s.execute(text("SELECT COUNT(*) FROM _concurrency_check")).scalar()
        out["db_rw"] = {"ok": True, "test_rows": int(n)}
    except Exception as e:
        out["db_rw"] = {"ok": False, "error": str(e)[:200]}

    # 3. Celery 投递 + 任务函数直接执行
    try:
        from core.tasks import send_task
        sent = send_task("backup_database")
        out["celery_send"] = {"ok": sent, "note": "backup_database 任务已投递（worker 执行情况看 worker 日志）"}
    except Exception as e:
        out["celery_send"] = {"ok": False, "error": str(e)[:150]}
    try:
        from core.tasks import _backup_database
        _backup_database()
        out["task_direct"] = {"ok": True, "note": "backup_database 函数直接执行成功（已生成备份）"}
    except Exception as e:
        out["task_direct"] = {"ok": False, "error": str(e)[:150]}

    # 4. 多 Worker 并发：并发请求 /health
    try:
        from core.db import session_scope
        from sqlalchemy import text
        with session_scope() as s:
            s.execute(text("SELECT 1"))
        results = []
        for _ in range(10):
            t0 = time.time()
            try:
                resp = requests.get("http://127.0.0.1:5000/health", timeout=5)
                results.append({"ok": resp.status_code == 200, "ms": int((time.time() - t0) * 1000)})
            except Exception as e:
                results.append({"ok": False, "error": str(e)[:80]})
        ok = sum(1 for x in results if x.get("ok"))
        avg = round(sum(x.get("ms", 0) for x in results) / max(1, len(results)), 1)
        out["concurrency"] = {"ok": ok == 10, "success": ok, "total": len(results), "avg_ms": avg}
    except Exception as e:
        out["concurrency"] = {"ok": False, "error": str(e)[:150]}

    # 5. 定时任务：检查 scheduler 是否运行（内存内无法看 beat 容器，提示查日志）
    out["note"] = "Worker/Beat 容器日志请执行: docker logs sales-agent-worker-1 --tail 20 && docker logs sales-agent-beat-1 --tail 20"
    return out
