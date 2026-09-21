"""销售提示词查看与编辑接口"""
from __future__ import annotations
import hashlib
from core import sql_compat as sqlite3  # SQL 统一指向 DATABASE_URL，避免与 ORM 分叉
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from config.settings import settings
from core.security import require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["prompt"], dependencies=[Depends(require_api_key)])

PROMPT_FILE = Path(settings.PROJECT_ROOT) / "config" / "sales_prompt.txt"
REQUIRED_KEYS = ["{context}", "{customer_profile}", "{stage}", "{chat_history}", "{input}"]

def _prompt_db():
    db = Path(settings.DATA_DIR) / "customers.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """CREATE TABLE IF NOT EXISTS prompt_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_hash TEXT,
            content TEXT,
            note TEXT DEFAULT '',
            created_at TEXT
        )"""
    )
    return conn

def _save_prompt_version(content: str, note: str = "") -> dict:
    conn = _prompt_db()
    cur = conn.execute(
        "INSERT INTO prompt_versions (content_hash, content, note, created_at) VALUES (?, ?, ?, ?)",
        (hashlib.md5(content.encode("utf-8")).hexdigest(), content, note,
         datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM prompt_versions WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return {"id": row[0], "note": row[3], "created_at": row[4]}


class PromptModel(BaseModel):
    content: str


@router.get("/system/prompt")
async def get_prompt():
    content = ""
    try:
        content = PROMPT_FILE.read_text(encoding="utf-8")
    except OSError:
        content = ""
    return {
        "content": content,
        "path": str(PROMPT_FILE),
        "updated_at": PROMPT_FILE.stat().st_mtime if PROMPT_FILE.exists() else 0,
    }


@router.put("/system/prompt", dependencies=[Depends(require_admin)])
async def update_prompt(req: PromptModel):
    content = (req.content or "").strip()
    if not content:
        return {"ok": False, "error": "提示词不能为空"}
    missing = [k for k in REQUIRED_KEYS if k not in content]
    if missing:
        return {"ok": False, "error": f"缺少必要占位符: {'、'.join(missing)}"}
    try:
        from langchain_classic.prompts import PromptTemplate
        PromptTemplate(
            template=content,
            input_variables=["context", "customer_profile", "stage", "chat_history", "input"],
        )
    except Exception as e:
        return {"ok": False, "error": f"提示词格式校验失败: {e}"}
    try:
        PROMPT_FILE.write_text(content, encoding="utf-8")
        _save_prompt_version(content, note="手动保存")
        from core.audit import audit
        audit(actor="admin", action="update_prompt", resource=str(PROMPT_FILE), detail=f"提示词长度 {len(content)}")
        return {"ok": True, "message": "提示词已保存并立即生效"}
    except OSError as e:
        return {"ok": False, "error": f"保存失败: {e}"}


@router.get("/system/prompt/versions")
async def prompt_versions(limit: int = 20):
    conn = _prompt_db()
    rows = conn.execute("SELECT id, content_hash, note, created_at FROM prompt_versions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return {"versions": [{"id": r[0], "content_hash": r[1], "note": r[2], "created_at": r[3]} for r in rows]}


@router.post("/system/prompt/versions/{version_id}/rollback", dependencies=[Depends(require_admin)])
async def rollback_prompt(version_id: int):
    conn = _prompt_db()
    row = conn.execute("SELECT content FROM prompt_versions WHERE id = ?", (version_id,)).fetchone()
    conn.close()
    if not row:
        return {"ok": False, "error": "版本不存在"}
    try:
        PROMPT_FILE.write_text(row[0], encoding="utf-8")
        _save_prompt_version(row[0], note=f"回滚自版本{version_id}")
        return {"ok": True, "message": f"已回滚到版本 {version_id}"}
    except OSError as e:
        return {"ok": False, "error": str(e)}


@router.post("/system/prompt/regression", dependencies=[Depends(require_admin)])
async def prompt_regression():
    from core.agent import sales_agent
    cases = [
        "课程多少钱？怎么参加活动？",
        "零基础能学会吗？有什么后续服务？",
        "太贵了，能便宜吗？",
    ]
    results = []
    import time
    for i, q in enumerate(cases, 1):
        try:
            t0 = time.time()
            reply = sales_agent.chat(q, f"regression-{i}", source="console")
            results.append({"question": q, "reply": reply, "seconds": round(time.time() - t0, 1)})
        except Exception as e:
            results.append({"question": q, "reply": f"调用失败: {e}", "seconds": 0})
    return {"ok": True, "results": results}
