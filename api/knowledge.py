"""租户级知识库接口：上传、审批、版本、重建和统计。"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select

from core.audit import audit
from core.db import init_db, session_scope
from core.knowledge_gaps import knowledge_gap_manager
from core.models import KnowledgeVersion
from core.security import (
    current_tenant,
    permission_required,
    require_admin,
    require_api_key,
)
from knowledge.knowledge_manager import KnowledgeManager

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1",
    tags=["knowledge"],
    dependencies=[Depends(require_api_key)],
)


class TextAdd(BaseModel):
    content: str
    title: str = ""


def _manager(tenant_id: int) -> KnowledgeManager:
    return KnowledgeManager(tenant_id=tenant_id)


def _safe_filename(name: str) -> str:
    return Path(name).name


def _safe_text(value: str) -> str:
    return str(value or "").encode("utf-8", errors="replace").decode("utf-8")


@router.get(
    "/knowledge/files",
    dependencies=[Depends(permission_required("knowledge:read"))],
)
async def list_files(request: Request):
    manager = _manager(current_tenant(request))
    return {
        "files": [
            {
                "name": _safe_text(path.name),
                "size": path.stat().st_size if path.exists() else 0,
                "modified": path.stat().st_mtime if path.exists() else 0,
            }
            for path in manager.list_knowledge_files()
        ]
    }


@router.get(
    "/knowledge/stats",
    dependencies=[Depends(permission_required("knowledge:read"))],
)
async def knowledge_stats(request: Request):
    return _manager(current_tenant(request)).get_stats()


@router.get(
    "/knowledge/versions",
    dependencies=[Depends(permission_required("knowledge:read"))],
)
async def list_versions(request: Request, limit: int = 200):
    init_db()
    with session_scope(read_only=True) as session:
        rows = session.execute(
            select(KnowledgeVersion)
            .where(KnowledgeVersion.tenant_id == current_tenant(request))
            .order_by(KnowledgeVersion.id.desc())
            .limit(limit)
        ).scalars().all()
    return {
        "versions": [
            {column.name: getattr(row, column.name) for column in row.__table__.columns}
            for row in rows
        ]
    }


@router.post("/knowledge/upload", dependencies=[Depends(require_admin)])
async def upload_knowledge(request: Request, file: UploadFile = File(...)):
    tenant_id = current_tenant(request)
    manager = _manager(tenant_id)
    filename = _safe_filename(file.filename or "knowledge.txt")
    content = await file.read()
    target = manager.knowledge_dir / filename
    target.write_bytes(content)
    init_db()
    with session_scope() as session:
        rows = session.execute(
            select(KnowledgeVersion).where(
                KnowledgeVersion.tenant_id == tenant_id,
                KnowledgeVersion.filename == filename,
            )
        ).scalars().all()
        version = len(rows) + 1
        row = KnowledgeVersion(
            tenant_id=tenant_id,
            filename=filename,
            version=version,
            file_hash=hashlib.md5(content).hexdigest(),
            size=len(content),
            active=False,
            status="pending",
        )
        session.add(row)
        session.flush()
    audit(
        actor="admin",
        action="knowledge_upload",
        resource=filename,
        detail="上传待审批",
        tenant_id=tenant_id,
    )
    return {
        "filename": filename,
        "imported": 0,
        "version": version,
        "status": "pending",
        "hint": "已上传，审批通过后重建索引生效",
    }


@router.post(
    "/knowledge/versions/{version_id}/approve",
    dependencies=[Depends(require_admin)],
)
async def approve_version(version_id: int, request: Request):
    tenant_id = current_tenant(request)
    filename = ""
    with session_scope() as session:
        row = session.execute(
            select(KnowledgeVersion).where(
                KnowledgeVersion.id == version_id,
                KnowledgeVersion.tenant_id == tenant_id,
            )
        ).scalars().first()
        if not row:
            return {"ok": False, "error": "版本不存在"}
        row.status = "approved"
        row.active = True
        row.reviewed_by = "admin"
        row.reviewed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        filename = row.filename
        session.flush()
    manager = _manager(tenant_id)
    count = manager.import_single_file(manager.knowledge_dir / filename)
    audit(
        actor="admin",
        action="knowledge_approve",
        resource=filename,
        detail=f"version={version_id}; imported={count}",
        tenant_id=tenant_id,
    )
    return {"ok": True, "filename": filename, "version": version_id, "imported": count}


@router.post(
    "/knowledge/versions/{version_id}/reject",
    dependencies=[Depends(require_admin)],
)
async def reject_version(version_id: int, request: Request):
    with session_scope() as session:
        row = session.execute(
            select(KnowledgeVersion).where(
                KnowledgeVersion.id == version_id,
                KnowledgeVersion.tenant_id == current_tenant(request),
            )
        ).scalars().first()
        if not row:
            return {"ok": False, "error": "版本不存在"}
        row.status = "rejected"
        row.active = False
        row.reviewed_by = "admin"
        row.reviewed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        session.flush()
    return {"ok": True, "version_id": version_id}


@router.post(
    "/knowledge/versions/{version_id}/rollback",
    dependencies=[Depends(require_admin)],
)
async def rollback_version(version_id: int, request: Request):
    tenant_id = current_tenant(request)
    with session_scope() as session:
        target = session.execute(
            select(KnowledgeVersion).where(
                KnowledgeVersion.id == version_id,
                KnowledgeVersion.tenant_id == tenant_id,
            )
        ).scalars().first()
        if not target:
            return {"ok": False, "error": "版本不存在"}
        filename = target.filename
        for row in session.execute(
            select(KnowledgeVersion).where(
                KnowledgeVersion.tenant_id == tenant_id,
                KnowledgeVersion.filename == filename,
            )
        ).scalars().all():
            row.active = row.id == version_id
            row.status = "approved" if row.id == version_id else "rejected"
    manager = _manager(tenant_id)
    count = manager.import_single_file(manager.knowledge_dir / filename)
    return {"ok": True, "filename": filename, "version": version_id, "imported": count}


@router.get(
    "/knowledge/gaps",
    dependencies=[Depends(permission_required("knowledge:read"))],
)
async def list_gaps(request: Request, limit: int = 200):
    return {
        "items": knowledge_gap_manager.list(
            limit=limit,
            tenant_id=current_tenant(request),
        )
    }


@router.post("/knowledge/gaps", dependencies=[Depends(require_admin)])
async def add_gap(req: TextAdd, request: Request):
    gap_id = knowledge_gap_manager.add(
        "",
        req.content,
        tenant_id=current_tenant(request),
    )
    return {"id": gap_id}


@router.delete("/knowledge/gaps/{gap_id}", dependencies=[Depends(require_admin)])
async def delete_gap(gap_id: int, request: Request):
    return {
        "deleted": knowledge_gap_manager.delete(
            gap_id,
            tenant_id=current_tenant(request),
        )
    }


@router.post("/knowledge/rebuild", dependencies=[Depends(require_admin)])
async def rebuild_knowledge(request: Request):
    tenant_id = current_tenant(request)
    manager = _manager(tenant_id)
    count = manager.import_from_directory(manager.knowledge_dir)
    audit(
        actor="admin",
        action="knowledge_rebuild",
        resource="all",
        detail=f"imported={count}",
        tenant_id=tenant_id,
    )
    return {"imported": count}


@router.post("/knowledge/text", dependencies=[Depends(require_admin)])
async def add_text(req: TextAdd, request: Request):
    tenant_id = current_tenant(request)
    ids = _manager(tenant_id).add_text(
        req.content,
        metadata={"title": req.title or "", "tenant_id": tenant_id},
    )
    audit(
        actor="admin",
        action="knowledge_text",
        resource=req.title or "text",
        detail=f"ids={len(ids)}",
        tenant_id=tenant_id,
    )
    return {"ids": ids}


@router.delete(
    "/knowledge/files/{filename}",
    dependencies=[Depends(require_admin)],
)
async def delete_knowledge(filename: str, request: Request):
    tenant_id = current_tenant(request)
    manager = _manager(tenant_id)
    safe = _safe_filename(filename)
    target = manager.knowledge_dir / safe
    if target.exists():
        target.unlink()
    count = manager.import_from_directory(manager.knowledge_dir)
    audit(
        actor="admin",
        action="knowledge_delete",
        resource=safe,
        detail=f"rebuilt={count}",
        tenant_id=tenant_id,
    )
    return {"deleted": safe, "rebuilt": count}
