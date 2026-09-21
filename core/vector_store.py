"""轻量向量库：fastembed 生成向量，JSON 持久化，无需 chromadb"""
from __future__ import annotations
import hashlib
import json
import logging
import math
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config.settings import settings
from core.db import session_scope
from core.llm import create_embeddings
from sqlalchemy import text

logger = logging.getLogger(__name__)

def _clean_text(value):
    if isinstance(value, str):
        return value.encode("utf-8", errors="replace").decode("utf-8")
    return value


class _SimpleRetriever:
    def __init__(self, store: "VectorStore", k: int):
        self._store = store
        self._k = k

    def get_relevant_documents(self, query: str) -> List[Document]:
        return [doc for doc, _ in self._store.similarity_search_with_score(query, k=self._k)]


class _Collection:
    def __init__(self, store: "VectorStore"):
        self._store = store

    def as_retriever(self, search_kwargs: Optional[Dict[str, Any]] = None):
        k = (search_kwargs or {}).get("k", settings.RAG_TOP_K)
        return _SimpleRetriever(self._store, k)

    def add_documents(self, docs: List[Document], ids: Optional[List[str]] = None) -> None:
        self._store.add_documents(docs)

    def delete(self, doc_ids: List[str]) -> None:
        self._store.delete_documents(doc_ids)

    def delete_collection(self) -> None:
        self._store.clear()

    def get(self, where: Optional[Dict[str, Any]] = None) -> Dict[str, list]:
        return {"ids": []}


class VectorStore:
    """轻量向量库：向量存 JSON 文件，余弦相似度检索"""

    def __init__(self, tenant_id: int = 0, index_version_id: int | None = None):
        self.tenant_id = int(tenant_id or 0)
        self.index_version_id = index_version_id
        self.embeddings = create_embeddings()
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.RAG_CHUNK_SIZE,
            chunk_overlap=settings.RAG_CHUNK_OVERLAP,
            separators=["\n\n", "\n", "。", "！", "？", " ", ""],
        )
        self._lock = threading.RLock()
        self._index_path = (
            Path(settings.DATA_DIR)
            / (
                "vector_index.json"
                if self.tenant_id == 0
                else f"vector_index_tenant_{self.tenant_id}.json"
            )
        )
        self._items: List[dict] = []
        self._collection = _Collection(self)
        self._load()

    @property
    def collection(self) -> _Collection:
        return self._collection

    def _load(self) -> None:
        try:
            if self._index_path.exists():
                data = json.loads(self._index_path.read_text(encoding="utf-8"))
                self._items = data.get("items", [])
        except Exception as e:
            logger.warning("向量索引读取失败，使用空索引: %s", e)
            self._items = []

    def _save(self) -> None:
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"items": self._items}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._index_path)

    def add_documents(self, documents: List[Document], batch_size: int = 32) -> List[str]:
        split_docs = self.text_splitter.split_documents(documents)
        if not split_docs:
            return []
        texts = [d.page_content for d in split_docs]
        vectors = self.embeddings.embed_documents(texts)
        added_ids: List[str] = []
        with self._lock:
            existing = {item.get("id") for item in self._items}
            for doc, vec in zip(split_docs, vectors):
                content_hash = hashlib.md5(doc.page_content.encode("utf-8")).hexdigest()
                doc_id = f"{doc.metadata.get('source', 'unknown')}_{content_hash}"
                if doc_id in existing:
                    continue
                self._items.append({
                    "id": doc_id,
                    "text": _clean_text(doc.page_content),
                    "metadata": {
                        **{k: _clean_text(v) for k, v in doc.metadata.items()},
                        "tenant_id": self.tenant_id,
                        "index_version_id": (
                            self.index_version_id
                            if self.index_version_id is not None
                            else doc.metadata.get("index_version_id")
                        ),
                    },
                    "embedding": [float(x) for x in vec],
                })
                existing.add(doc_id)
                added_ids.append(doc_id)
            self._save()
        return added_ids

    def similarity_search_with_score(self, query: str, k: int = None) -> List[Tuple[Document, float]]:
        k = k or settings.RAG_TOP_K
        query_vec = self.embeddings.embed_query(query)
        with self._lock:
            scored = []
            for item in self._items:
                metadata = item.get("metadata") or {}
                if int(metadata.get("tenant_id", 0) or 0) != self.tenant_id:
                    continue
                if (
                    self.index_version_id is not None
                    and metadata.get("index_version_id") not in (None, self.index_version_id)
                ):
                    continue
                cosine = self._cosine(query_vec, item["embedding"])
                keyword = self._keyword_score(query, item.get("text") or "")
                scored.append((item, round(cosine * 0.7 + keyword * 0.3, 4)))
        scored.sort(key=lambda x: x[1], reverse=True)
        results: List[Tuple[Document, float]] = []
        for item, score in scored[:k]:
            doc = Document(page_content=item["text"], metadata=item.get("metadata") or {})
            results.append((doc, max(0.0, min(1.0, score))))
        return results

    def similarity_search(self, query: str, k: int = None, filter: Optional[Dict[str, Any]] = None) -> List[Document]:
        return [doc for doc, _ in self.similarity_search_with_score(query, k=k)]

    @staticmethod
    def _keyword_score(query: str, text: str) -> float:
        def grams(value: str) -> set:
            tokens = re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+", value or "")
            result = set()
            for token in tokens:
                if len(token) >= 2:
                    for i in range(len(token) - 1):
                        result.add(token[i:i + 2])
                else:
                    result.add(token)
            return result
        qg = grams(query)
        if not qg:
            return 0.0
        tg = grams(text)
        return len(qg & tg) / len(qg)

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    def delete_documents(self, doc_ids: List[str]) -> None:
        remove = set(doc_ids)
        with self._lock:
            self._items = [item for item in self._items if item.get("id") not in remove]
            self._save()

    def count(self) -> int:
        return sum(
            1
            for item in self._items
            if int((item.get("metadata") or {}).get("tenant_id", 0) or 0)
            == self.tenant_id
        )

    def clear(self) -> None:
        with self._lock:
            self._items = [
                item
                for item in self._items
                if int((item.get("metadata") or {}).get("tenant_id", 0) or 0)
                != self.tenant_id
            ]
            self._save()


class PgVectorStore:
    """PostgreSQL + pgvector 后端；失败时由 KnowledgeStore 回退 JSON。"""

    def __init__(self, tenant_id: int, index_version_id: int | None = None):
        self.tenant_id = int(tenant_id or 0)
        self.index_version_id = index_version_id
        self.embeddings = create_embeddings()
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.RAG_CHUNK_SIZE,
            chunk_overlap=settings.RAG_CHUNK_OVERLAP,
            separators=["\n\n", "\n", "。", "！", "？", " ", ""],
        )

    @staticmethod
    def available() -> bool:
        try:
            with session_scope(read_only=True) as session:
                if session.bind.dialect.name != "postgresql":
                    return False
                session.execute(text("SELECT 1 FROM pg_extension WHERE extname='vector'"))
            return True
        except Exception:
            return False

    def add_documents(
        self,
        documents: List[Document],
        document_id: int | None = None,
        index_version_id: int | None = None,
    ) -> List[str]:
        split_docs = self.text_splitter.split_documents(documents)
        if not split_docs:
            return []
        vectors = self.embeddings.embed_documents(
            [doc.page_content for doc in split_docs]
        )
        version_id = (
            index_version_id
            if index_version_id is not None
            else self.index_version_id
        )
        ids: List[str] = []
        with session_scope() as session:
            for index, (doc, vector) in enumerate(zip(split_docs, vectors)):
                content = _clean_text(doc.page_content)
                doc_id = (
                    f"t{self.tenant_id}:v{version_id or 0}:"
                    f"{hashlib.md5(content.encode('utf-8')).hexdigest()}"
                )
                metadata = {
                    **{
                        key: _clean_text(value)
                        for key, value in doc.metadata.items()
                    },
                    "tenant_id": self.tenant_id,
                    "index_version_id": version_id,
                    "document_id": document_id,
                }
                exists = session.execute(
                    text(
                        "SELECT 1 FROM knowledge_chunks "
                        "WHERE tenant_id=:tenant_id "
                        "AND index_version_id=:version_id "
                        "AND content=:content LIMIT 1"
                    ),
                    {
                        "tenant_id": self.tenant_id,
                        "version_id": version_id,
                        "content": content,
                    },
                ).first()
                if exists:
                    continue
                session.execute(
                    text(
                        "INSERT INTO knowledge_chunks "
                        "(tenant_id, document_id, index_version_id, chunk_index, "
                        "content, metadata_json, embedding_json, embedding_vector, created_at) "
                        "VALUES (:tenant_id, :document_id, :version_id, :chunk_index, "
                        ":content, :metadata_json, :embedding_json, "
                        "CAST(:embedding_vector AS vector), :created_at)"
                    ),
                    {
                        "tenant_id": self.tenant_id,
                        "document_id": document_id,
                        "version_id": version_id,
                        "chunk_index": index,
                        "content": content,
                        "metadata_json": json.dumps(metadata, ensure_ascii=False),
                        "embedding_json": json.dumps(vector),
                        "embedding_vector": json.dumps(vector),
                        "created_at": datetime.now().strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                    },
                )
                ids.append(doc_id)
        return ids

    def similarity_search_with_score(
        self,
        query: str,
        k: int = None,
        index_version_id: int | None = None,
    ) -> List[Tuple[Document, float]]:
        k = k or settings.RAG_TOP_K
        vector = self.embeddings.embed_query(query)
        version_id = (
            index_version_id
            if index_version_id is not None
            else self.index_version_id
        )
        params = {
            "tenant_id": self.tenant_id,
            "embedding": json.dumps(vector),
            "limit": max(k * 3, k),
        }
        version_filter = ""
        if version_id is not None:
            version_filter = "AND kc.index_version_id=:version_id "
            params["version_id"] = version_id
        with session_scope(read_only=True) as session:
            rows = session.execute(
                text(
                    "SELECT kc.content, kc.metadata_json, "
                    "1 - (kc.embedding_vector <=> CAST(:embedding AS vector)) AS score "
                    "FROM knowledge_chunks kc "
                    "WHERE kc.tenant_id=:tenant_id "
                    "AND kc.embedding_vector IS NOT NULL "
                    f"{version_filter}"
                    "ORDER BY kc.embedding_vector <=> CAST(:embedding AS vector) "
                    "LIMIT :limit"
                ),
                params,
            ).fetchall()
        results: List[Tuple[Document, float]] = []
        for row in rows:
            try:
                metadata = json.loads(row[1] or "{}")
            except (TypeError, ValueError):
                metadata = {}
            score = float(row[2] or 0)
            score = 0.7 * max(0.0, min(1.0, score)) + 0.3 * VectorStore._keyword_score(
                query,
                row[0] or "",
            )
            results.append(
                (
                    Document(page_content=row[0] or "", metadata=metadata),
                    max(0.0, min(1.0, score)),
                )
            )
        results.sort(key=lambda item: item[1], reverse=True)
        return results[:k]

    def delete_index_version(self, version_id: int) -> None:
        with session_scope() as session:
            session.execute(
                text(
                    "DELETE FROM knowledge_chunks "
                    "WHERE tenant_id=:tenant_id AND index_version_id=:version_id"
                ),
                {"tenant_id": self.tenant_id, "version_id": int(version_id)},
            )

    def clear(self) -> None:
        with session_scope() as session:
            session.execute(
                text("DELETE FROM knowledge_chunks WHERE tenant_id=:tenant_id"),
                {"tenant_id": self.tenant_id},
            )

    def count(self) -> int:
        with session_scope(read_only=True) as session:
            row = session.execute(
                text(
                    "SELECT COUNT(*) FROM knowledge_chunks "
                    "WHERE tenant_id=:tenant_id"
                ),
                {"tenant_id": self.tenant_id},
            ).first()
        return int(row[0] if row else 0)


class KnowledgeStore:
    """按租户选择 pgvector；不可用时回退到租户隔离的 JSON 索引。"""

    def __init__(self, tenant_id: int = 0, index_version_id: int | None = None):
        self.tenant_id = int(tenant_id or 0)
        self.index_version_id = index_version_id
        self.backend_name = "json"
        self.backend = VectorStore(
            tenant_id=self.tenant_id,
            index_version_id=index_version_id,
        )
        if (
            str(getattr(settings, "RAG_BACKEND", "auto") or "auto").lower()
            in ("auto", "pgvector")
            and PgVectorStore.available()
        ):
            self.backend_name = "pgvector"
            self.backend = PgVectorStore(
                tenant_id=self.tenant_id,
                index_version_id=index_version_id,
            )

    def add_documents(
        self,
        documents: List[Document],
        document_id: int | None = None,
        index_version_id: int | None = None,
    ) -> List[str]:
        if self.backend_name == "pgvector":
            return self.backend.add_documents(
                documents,
                document_id=document_id,
                index_version_id=index_version_id,
            )
        return self.backend.add_documents(documents)

    def similarity_search_with_score(
        self,
        query: str,
        k: int | None = None,
        index_version_id: int | None = None,
    ) -> List[Tuple[Document, float]]:
        try:
            if self.backend_name == "pgvector":
                return self.backend.similarity_search_with_score(
                    query,
                    k=k,
                    index_version_id=index_version_id,
                )
            return self.backend.similarity_search_with_score(query, k=k)
        except Exception as exc:
            logger.warning("pgvector 检索失败，回退 JSON 索引: %s", exc)
            fallback = VectorStore(
                tenant_id=self.tenant_id,
                index_version_id=index_version_id,
            )
            return fallback.similarity_search_with_score(query, k=k)

    def delete_index_version(self, version_id: int) -> None:
        if self.backend_name == "pgvector":
            self.backend.delete_index_version(version_id)

    def clear(self) -> None:
        self.backend.clear()

    def count(self) -> int:
        return self.backend.count()
