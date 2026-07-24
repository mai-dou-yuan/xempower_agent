from __future__ import annotations

import os
from typing import Sequence

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from ..config import Settings
from ..errors import AgentError


class QwenEmbeddingClient:
    """Small wrapper around DashScope's OpenAI-compatible text embedding API."""

    batch_size = 20

    def __init__(self, settings: Settings):
        if not settings.dashscope_api_key:
            raise AgentError(
                "embedding_not_configured",
                "未配置 DASHSCOPE_API_KEY，无法执行 Qwen 向量检索。",
                status_code=503,
            )
        self.model = settings.dashscope_embedding_model
        self.dimensions = settings.dashscope_embedding_dimensions
        self.api_key = settings.dashscope_api_key
        self.base_url = settings.dashscope_base_url
        self.timeout = settings.dashscope_timeout_seconds
        self.client: OpenAI | None = None

    def _client(self) -> OpenAI:
        if self.client is None:
            # Prefer the HTTP proxy variables documented for this workspace.  Do
            # not inherit ALL_PROXY: it may point to SOCKS without socksio.
            proxy = os.getenv("https_proxy") or os.getenv("HTTPS_PROXY") or os.getenv("http_proxy") or os.getenv("HTTP_PROXY")
            http_client = httpx.Client(proxy=proxy, trust_env=False) if proxy else httpx.Client(trust_env=False)
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
                http_client=http_client,
            )
        return self.client

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        try:
            for start in range(0, len(texts), self.batch_size):
                response = self._client().embeddings.create(
                    model=self.model,
                    input=list(texts[start : start + self.batch_size]),
                    dimensions=self.dimensions,
                )
                ordered = sorted(response.data, key=lambda item: item.index)
                vectors.extend([item.embedding for item in ordered])
        except (APIConnectionError, APITimeoutError) as exc:
            raise AgentError("embedding_unavailable", "Qwen 向量服务当前不可用。", status_code=503) from exc
        except APIStatusError as exc:
            raise AgentError(
                "embedding_request_failed",
                f"Qwen 向量服务请求失败（HTTP {exc.status_code}）。",
                status_code=503,
            ) from exc
        if len(vectors) != len(texts):
            raise AgentError("embedding_invalid_response", "Qwen 向量服务返回的向量数量异常。", status_code=503)
        if any(len(vector) != self.dimensions for vector in vectors):
            raise AgentError("embedding_invalid_response", "Qwen 向量服务返回的向量维度异常。", status_code=503)
        return vectors
