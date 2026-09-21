"""数据备份：SQLite 与向量索引的手动/定时备份"""
from __future__ import annotations
import datetime
import logging
import shutil
from pathlib import Path

from config.settings import settings

logger = logging.getLogger(__name__)

BACKUP_FILES = ("customers.db", "metrics.db", "llm_usage.db", "vector_index.json")


def backup_data(retain: int = 7) -> dict:
    data_dir = Path(settings.DATA_DIR)
    stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    target = data_dir / "backups" / f"backup-{stamp}"
    target.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in BACKUP_FILES:
        src = data_dir / name
        if src.exists():
            shutil.copy2(src, target / name)
            copied.append(name)
    for src in sorted(data_dir.glob("vector_index_tenant_*.json")):
        shutil.copy2(src, target / src.name)
        copied.append(src.name)
    knowledge_dir = data_dir / "knowledge_base"
    if knowledge_dir.exists():
        shutil.copytree(knowledge_dir, target / "knowledge_base", dirs_exist_ok=True)
        copied.append("knowledge_base")

    root = data_dir / "backups"
    if root.exists():
        dirs = sorted([d for d in root.iterdir() if d.is_dir()], key=lambda x: x.name)
        for old in dirs[:-retain]:
            try:
                shutil.rmtree(old, ignore_errors=True)
            except Exception as e:
                logger.warning(f"旧备份清理失败 {old}: {e}")
    return {"dir": str(target), "files": copied}


def archive_backup() -> dict:
    """把最近一次备份归档到对象存储（未配置时落到本地 object_store）"""
    info = last_backup()
    if not info["exists"]:
        return {"ok": False, "error": "还没有备份"}
    from core.object_storage import upload_backup
    root = Path(settings.DATA_DIR) / "backups"
    results = upload_backup(root / info["last"])
    ok = sum(1 for r in results if r.get("ok"))
    return {"ok": bool(results), "uploaded": ok, "results": results[:20]}

def last_backup() -> dict:
    root = Path(settings.DATA_DIR) / "backups"
    if not root.exists():
        return {"exists": False, "last": "", "count": 0}
    dirs = sorted([d for d in root.iterdir() if d.is_dir()], key=lambda x: x.name, reverse=True)
    return {"exists": bool(dirs), "last": dirs[0].name if dirs else "", "count": len(dirs)}
