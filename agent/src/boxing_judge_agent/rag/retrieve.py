from __future__ import annotations

import json
import math
from pathlib import Path

from ..config import Settings, get_settings
from ..errors import AgentError
from ..schemas import EvidenceRef
from .embedding import QwenEmbeddingClient
from .ingest import parse_knowledge_base


DOMAIN_TERMS = {
    "scoring_evidence": "合法计分拳 有效击打区域 干净 力量 效果 进攻性 优势",
    "round_scoring": "10-Point Must 回合 基础比分 胜负 扣分 分离 争议",
    "authority": "Judge Referee 权限 击倒 犯规 扣分 正式裁定",
    "knockdown": "击倒 10-8 正式裁定 一次击倒 不是无条件",
    "foul_deduction": "犯规 警告 扣分 权限 基础比分",
}


def _cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


class RuleRetriever:
    def __init__(
        self,
        knowledge_base: str | Path,
        index_path: str | Path | None = None,
        *,
        settings: Settings | None = None,
        embedder: QwenEmbeddingClient | None = None,
    ):
        self.knowledge_base = Path(knowledge_base)
        self.index_path = Path(index_path) if index_path else None
        self.settings = settings or get_settings()
        self.embedder = embedder or QwenEmbeddingClient(self.settings)
        if self.index_path and self.index_path.exists():
            self.index = json.loads(self.index_path.read_text(encoding="utf-8"))
        else:
            self.index = parse_knowledge_base(self.knowledge_base)
        self.chunks = self.index["chunks"]
        self.vectors = self._load_or_create_vectors()

    def _load_or_create_vectors(self) -> list[list[float]]:
        metadata = self.index.get("embedding")
        vectors = self.index.get("vectors")
        expected = {
            "provider": "dashscope",
            "model": self.embedder.model,
            "dimensions": self.embedder.dimensions,
        }
        if metadata == expected and isinstance(vectors, list) and len(vectors) == len(self.chunks):
            return vectors
        texts = [" ".join(chunk["heading_path"]) + "\n" + chunk["text"] for chunk in self.chunks]
        vectors = self.embedder.embed(texts)
        self.index["embedding"] = expected
        self.index["vectors"] = vectors
        if self.index_path:
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
            self.index_path.write_text(json.dumps(self.index, ensure_ascii=False), encoding="utf-8")
        return vectors

    def retrieve(self, query: str, *, domain: str | None = None, top_k: int = 6) -> list[EvidenceRef]:
        expanded = query + " " + DOMAIN_TERMS.get(domain or "", "")
        query_vector = self.embedder.embed([expanded])[0]
        scores = [_cosine(query_vector, vector) for vector in self.vectors]
        ranked = sorted(range(len(self.chunks)), key=lambda index: scores[index], reverse=True)
        selected = [index for index in ranked[:top_k] if scores[index] > 0]
        if domain in {"round_scoring", "knockdown", "scoring_evidence"}:
            for index, chunk in enumerate(self.chunks):
                if "ambiguity" in chunk["rule_domains"] and index not in selected:
                    selected.append(index)
        unique = selected[: top_k + 2]
        max_score = max((scores[index] for index in unique), default=1.0) or 1.0
        return [EvidenceRef(**self.chunks[index], retrieval_score=round(scores[index] / max_score, 6)) for index in unique]

    def retrieve_batch(
        self,
        signatures: list[str],
        *,
        user_query: str | None = None,
    ) -> list[EvidenceRef]:
        evidence: dict[str, EvidenceRef] = {}
        queries: list[tuple[str, str | None]] = []
        if user_query:
            # The user's natural-language goal is embedded independently. It can
            # broaden or focus retrieval, but cannot replace the mandatory rule
            # signatures derived from the CSV.
            queries.append((user_query, None))
        queries.extend((signature, signature.split(":", 1)[0]) for signature in signatures)
        for query, domain in queries:
            for item in self.retrieve(query, domain=domain):
                existing = evidence.get(item.chunk_id)
                if existing is None or item.retrieval_score > existing.retrieval_score:
                    evidence[item.chunk_id] = item
        return list(evidence.values())


def retrieve_rule_evidence(
    knowledge_base: str | Path,
    signatures: list[str],
    index_path: str | Path | None = None,
    *,
    settings: Settings | None = None,
    user_query: str | None = None,
) -> list[EvidenceRef]:
    return RuleRetriever(knowledge_base, index_path, settings=settings).retrieve_batch(
        signatures,
        user_query=user_query,
    )
