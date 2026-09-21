"""
RAG 检索增强生成模块
"""
from __future__ import annotations
import threading
from typing import Optional, Dict, Any, List
from langchain_classic.chains import RetrievalQA
from langchain_classic.prompts import PromptTemplate
from langchain_core.documents import Document
from config.settings import settings
from core.llm import create_llm
from core.vector_store import VectorStore

SALES_SYSTEM_PROMPT = """你是一位专业的销售客服助手。请基于以下参考信息回答问题。

原则：
1. 只使用参考信息回答，不编造
2. 信息不足时如实告知
3. 保持礼貌、耐心、专业
4. 回答简洁清晰

参考信息：
{context}

历史对话：
{chat_history}

客户问题：{question}

回答："""

class RAGEngine:
    def __init__(self):
        self._llm = None
        self._stores = {}
        self._qa_chain = None
        self._lock = threading.Lock()

    @property
    def llm(self):
        if self._llm is None:
            with self._lock:
                if self._llm is None:
                    self._llm = create_llm()
        return self._llm

    def vector_store(
        self,
        tenant_id: int = 0,
        index_version_id: int | None = None,
    ):
        from core.vector_store import KnowledgeStore

        key = (int(tenant_id or 0), index_version_id)
        store = self._stores.get(key)
        if store is None:
            with self._lock:
                store = self._stores.get(key)
                if store is None:
                    store = KnowledgeStore(
                        tenant_id=key[0],
                        index_version_id=index_version_id,
                    )
                    self._stores[key] = store
        return store

    @property
    def qa_chain(self) -> RetrievalQA:
        if self._qa_chain is None:
            with self._lock:
                if self._qa_chain is None:
                    prompt = PromptTemplate(
                        template=SALES_SYSTEM_PROMPT,
                        input_variables=["context", "chat_history", "question"],
                    )
                    self._qa_chain = RetrievalQA.from_chain_type(
                        llm=self.llm,
                        chain_type="stuff",
                        retriever=self.vector_store().backend.collection.as_retriever(
                            search_kwargs={"k": settings.RAG_TOP_K}
                        ),
                        chain_type_kwargs={"prompt": prompt, "verbose": True},
                        return_source_documents=True,
                    )
        return self._qa_chain

    def query(self, question: str, chat_history: str = "", filter: Optional[Dict[str,Any]] = None) -> dict:
        result = self.qa_chain.invoke({"query": question, "chat_history": chat_history})
        return {"result": result["result"], "source_documents": result.get("source_documents", [])}

    def query_with_scores(
        self,
        question: str,
        k: int = None,
        tenant_id: int = 0,
        index_version_id: int | None = None,
    ) -> List[tuple[Document, float]]:
        return self.vector_store(
            tenant_id=tenant_id,
            index_version_id=index_version_id,
        ).similarity_search_with_score(
            question,
            k=k or settings.RAG_TOP_K,
            index_version_id=index_version_id,
        )

    def add_knowledge(
        self,
        documents: List[Document],
        tenant_id: int = 0,
        document_id: int | None = None,
        index_version_id: int | None = None,
    ) -> List[str]:
        return self.vector_store(
            tenant_id=tenant_id,
            index_version_id=index_version_id,
        ).add_documents(
            documents,
            document_id=document_id,
            index_version_id=index_version_id,
        )

rag_engine = RAGEngine()
