"""租户级知识库：文档、切片、索引版本和检索入口。"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from langchain_community.document_loaders import (
    CSVLoader,
    Docx2txtLoader,
    JSONLoader,
    PyPDFLoader,
    TextLoader,
)
from langchain_core.documents import Document
from sqlalchemy import select

from config.settings import settings
from core.db import init_db, session_scope
from core.models import KnowledgeDocument, KnowledgeIndexVersion, KnowledgeVersion

logger = logging.getLogger(__name__)


LOADER_MAP = {
    ".txt": TextLoader,
    ".md": TextLoader,
    ".csv": CSVLoader,
    ".pdf": PyPDFLoader,
    ".docx": Docx2txtLoader,
    ".doc": Docx2txtLoader,
    ".xlsx": CSVLoader,
    ".xls": CSVLoader,
    ".html": TextLoader,
    ".htm": TextLoader,
    ".json": JSONLoader,
}

SUPPORTED_EXTENSIONS = list(LOADER_MAP.keys())


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class KnowledgeManager:
    """按租户隔离知识文件和向量索引。"""

    def __init__(self, tenant_id: int = 0):
        self.tenant_id = int(tenant_id or 0)
        base = Path(settings.KNOWLEDGE_BASE_DIR)
        self.knowledge_dir = (
            base if self.tenant_id == 0 else base / f"tenant_{self.tenant_id}"
        )
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        init_db()

    def list_knowledge_files(self) -> List[Path]:
        files: list[Path] = []
        for ext in SUPPORTED_EXTENSIONS:
            files.extend(list(self.knowledge_dir.glob(f"*{ext}")))
        return sorted(files)

    def load_single_file(self, file_path: Path) -> List[Document]:
        ext = file_path.suffix.lower()
        if ext not in LOADER_MAP:
            raise ValueError(f"不支持的文件格式: {ext}")
        loader_class = LOADER_MAP[ext]
        kwargs = {}
        if ext in (".txt", ".md", ".html", ".htm", ".csv", ".xlsx", ".xls"):
            kwargs["encoding"] = "utf-8"
        try:
            docs = loader_class(str(file_path), **kwargs).load()
            for doc in docs:
                doc.metadata.update(
                    {
                        "tenant_id": self.tenant_id,
                        "source": str(file_path),
                        "source_ext": ext,
                        "source_filename": file_path.name,
                    }
                )
            return docs
        except Exception as exc:
            logger.error("加载文件失败 %s: %s", file_path, exc)
            return []

    def _blocked_files(self) -> set[str]:
        with session_scope(read_only=True) as session:
            rows = session.execute(
                select(KnowledgeVersion)
                .where(KnowledgeVersion.tenant_id == self.tenant_id)
                .order_by(KnowledgeVersion.id.desc())
            ).scalars().all()
        latest: dict[str, str] = {}
        for row in rows:
            latest.setdefault(row.filename, row.status or "pending")
        return {
            filename
            for filename, status in latest.items()
            if status in ("pending", "rejected")
        }

    def import_from_directory(self, directory: Optional[Path] = None) -> int:
        target_dir = directory or self.knowledge_dir
        files = [
            path
            for path in self.list_knowledge_files()
            if path.parent == target_dir
        ]
        return self._import_files(files)

    def import_single_file(self, file_path: Path) -> int:
        if not Path(file_path).exists():
            return 0
        return self._import_files([Path(file_path)])

    def add_text(self, text: str, metadata: Optional[dict] = None) -> List[str]:
        return self.add_documents(
            [Document(page_content=text, metadata=metadata or {})]
        )

    def add_documents(self, documents: List[Document]) -> List[str]:
        if not documents:
            return []
        from core.vector_store import KnowledgeStore

        with session_scope() as session:
            version = KnowledgeIndexVersion(
                tenant_id=self.tenant_id,
                version_name=f"manual-{int(datetime.now().timestamp())}",
                status="building",
                created_at=_now(),
            )
            session.add(version)
            session.flush()
            document = KnowledgeDocument(
                tenant_id=self.tenant_id,
                filename=str((documents[0].metadata or {}).get("title") or "手动文本"),
                source_path="",
                file_hash=hashlib.sha256(
                    "\n".join(doc.page_content for doc in documents).encode("utf-8")
                ).hexdigest(),
                size=sum(len(doc.page_content.encode("utf-8")) for doc in documents),
                status="approved",
                active=True,
                version=1,
                metadata_json="{}",
                created_at=_now(),
                updated_at=_now(),
            )
            session.add(document)
            session.flush()
            version_id = version.id
            document_id = document.id

        try:
            for doc in documents:
                doc.metadata.update(
                    {
                        "tenant_id": self.tenant_id,
                        "index_version_id": version_id,
                        "document_id": document_id,
                    }
                )
            ids = KnowledgeStore(
                tenant_id=self.tenant_id,
                index_version_id=version_id,
            ).add_documents(
                documents,
                document_id=document_id,
                index_version_id=version_id,
            )
            with session_scope() as session:
                version = session.get(KnowledgeIndexVersion, version_id)
                if version:
                    version.status = "active"
                    version.chunk_count = len(ids)
                    version.activated_at = _now()
                for old in session.execute(
                    select(KnowledgeIndexVersion).where(
                        KnowledgeIndexVersion.tenant_id == self.tenant_id,
                        KnowledgeIndexVersion.id != version_id,
                        KnowledgeIndexVersion.status == "active",
                    )
                ).scalars().all():
                    old.status = "retired"
                    old.retired_at = _now()
            return ids
        except Exception:
            with session_scope() as session:
                version = session.get(KnowledgeIndexVersion, version_id)
                if version:
                    version.status = "failed"
                    version.error = "embedding_failed"
            raise

    def _import_files(self, files: list[Path]) -> int:
        from core.vector_store import KnowledgeStore

        blocked = self._blocked_files()
        selected = [
            path
            for path in files
            if path.exists() and path.name not in blocked
        ]
        if not selected:
            return 0
        with session_scope() as session:
            version = KnowledgeIndexVersion(
                tenant_id=self.tenant_id,
                version_name=f"build-{int(datetime.now().timestamp())}",
                status="building",
                created_at=_now(),
            )
            session.add(version)
            session.flush()
            version_id = version.id

        imported = 0
        try:
            store = KnowledgeStore(
                tenant_id=self.tenant_id,
                index_version_id=version_id,
            )
            for path in selected:
                docs = self.load_single_file(path)
                if not docs:
                    continue
                content_bytes = path.read_bytes()
                file_hash = hashlib.sha256(content_bytes).hexdigest()
                with session_scope() as session:
                    latest = session.execute(
                        select(KnowledgeDocument)
                        .where(
                            KnowledgeDocument.tenant_id == self.tenant_id,
                            KnowledgeDocument.filename == path.name,
                        )
                        .order_by(KnowledgeDocument.id.desc())
                    ).scalars().first()
                    document = KnowledgeDocument(
                        tenant_id=self.tenant_id,
                        filename=path.name,
                        source_path=str(path),
                        file_hash=file_hash,
                        size=len(content_bytes),
                        status="approved",
                        active=True,
                        version=int((latest.version if latest else 0) or 0) + 1,
                        metadata_json="{}",
                        created_at=_now(),
                        updated_at=_now(),
                    )
                    session.add(document)
                    if latest:
                        latest.active = False
                        latest.status = "superseded"
                    session.flush()
                    document_id = document.id
                    knowledge_version = KnowledgeVersion(
                        tenant_id=self.tenant_id,
                        filename=path.name,
                        version=document.version,
                        file_hash=file_hash,
                        size=len(content_bytes),
                        active=True,
                        status="approved",
                        document_id=document_id,
                        index_version_id=version_id,
                        reviewed_by="system",
                        reviewed_at=_now(),
                        created_at=_now(),
                    )
                    session.add(knowledge_version)
                    session.flush()
                    for old in session.execute(
                        select(KnowledgeVersion).where(
                            KnowledgeVersion.tenant_id == self.tenant_id,
                            KnowledgeVersion.filename == path.name,
                            KnowledgeVersion.id != knowledge_version.id,
                        )
                    ).scalars().all():
                        old.active = False
                for doc in docs:
                    doc.metadata.update(
                        {
                            "tenant_id": self.tenant_id,
                            "index_version_id": version_id,
                            "document_id": document_id,
                        }
                    )
                store.add_documents(
                    docs,
                    document_id=document_id,
                    index_version_id=version_id,
                )
                imported += len(docs)

            with session_scope() as session:
                version = session.get(KnowledgeIndexVersion, version_id)
                if version:
                    version.status = "active"
                    version.chunk_count = store.count()
                    version.activated_at = _now()
                for old in session.execute(
                    select(KnowledgeIndexVersion).where(
                        KnowledgeIndexVersion.tenant_id == self.tenant_id,
                        KnowledgeIndexVersion.id != version_id,
                        KnowledgeIndexVersion.status == "active",
                    )
                ).scalars().all():
                    old.status = "retired"
                    old.retired_at = _now()
            return imported
        except Exception as exc:
            with session_scope() as session:
                version = session.get(KnowledgeIndexVersion, version_id)
                if version:
                    version.status = "failed"
                    version.error = str(exc)[:1000]
            raise

    def get_stats(self) -> dict:
        from core.vector_store import KnowledgeStore

        store = KnowledgeStore(tenant_id=self.tenant_id)
        return {
            "tenant_id": self.tenant_id,
            "vector_count": store.count(),
            "embedding_available": True,
            "vector_backend": store.backend_name,
            "source_files": len(self.list_knowledge_files()),
            "supported_formats": SUPPORTED_EXTENSIONS,
            "knowledge_dir": str(self.knowledge_dir),
        }
