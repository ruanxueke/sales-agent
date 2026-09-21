"""
LLM 工厂 - DeepSeek V4 Flash + 本地嵌入模型
"""
from __future__ import annotations
from langchain_openai import ChatOpenAI
from config.settings import settings

class FastEmbedEmbeddings:
    """基于 fastembed（ONNX）的轻量中文嵌入模型，无需 PyTorch"""

    def __init__(self, model_name: str):
        from fastembed import TextEmbedding
        self._model = TextEmbedding(model_name=model_name)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vec.tolist() for vec in self._model.embed(list(texts))]

    def embed_query(self, text: str) -> list[float]:
        return self._model.query_embed(text).tolist()


class DashScopeEmbeddings:
    """阿里云百炼文本向量接口，无需本地模型"""

    def __init__(self, model_name: str, api_key: str, url: str = ""):
        self._model = model_name or "text-embedding-v4"
        self._api_key = api_key or ""
        self._url = url or "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"

    def _embed(self, texts: list[str]) -> list[list[float]]:
        import requests
        resp = requests.post(
            self._url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self._model, "input": {"texts": list(texts)}},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings = sorted(
            data["output"]["embeddings"],
            key=lambda item: item.get("text_index", 0),
        )
        return [item["embedding"] for item in embeddings]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float]] = []
        batch_size = 8
        for i in range(0, len(texts), batch_size):
            results.extend(self._embed(texts[i:i + batch_size]))
        return results

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]


def create_llm():
    from core.secrets import resolve
    provider = settings.LLM_PROVIDER.lower()
    if provider == "deepseek":
        return ChatOpenAI(
            model=settings.LLM_MODEL or "deepseek-chat",
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
            api_key=resolve(settings.DEEPSEEK_API_KEY or ""),
            base_url=settings.DEEPSEEK_BASE_URL,
        )
    raise ValueError(f"不支持的 LLM 提供商: {provider}")

def create_embeddings():
    provider = settings.EMBEDDING_PROVIDER.lower()
    if provider in ("huggingface", "fastembed", "local"):
        return FastEmbedEmbeddings(settings.EMBEDDING_MODEL)
    if provider == "dashscope":
        from core.secrets import resolve
        return DashScopeEmbeddings(
            settings.EMBEDDING_MODEL,
            resolve(settings.DASHSCOPE_API_KEY or ""),
            settings.DASHSCOPE_EMBEDDING_URL,
        )
    raise ValueError(f"不支持的嵌入模型提供商: {provider}")
