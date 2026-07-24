from __future__ import annotations

from boxing_judge_agent.rag.ingest import parse_knowledge_base, rebuild_index
from boxing_judge_agent.rag.retrieve import RuleRetriever
from boxing_judge_agent.config import Settings


def test_ingest_metadata_and_retrieval(tmp_path):
    source = tmp_path / "kb.md"
    source.write_text(
        "# 规则\n## 4. 有效击打\n### 4.1 计分拳\n合法且计分的击打需要命中有效区域。\n"
        "## 16. 歧义\n### 16.8 Scoring Blow\n该术语范围需要确认。\n",
        encoding="utf-8",
    )
    parsed = parse_knowledge_base(source)
    assert parsed["knowledge_base_hash"]
    assert all(x["chunk_id"] and x["parent_id"] for x in parsed["chunks"])
    index = tmp_path / "index.json"
    settings = Settings(dashscope_api_key="test-key")
    rebuilt = rebuild_index(source, index, settings=settings)
    assert rebuilt["chunk_count"] == 2
    hits = RuleRetriever(source, index, settings=settings).retrieve("合法计分拳需要什么证据", domain="scoring_evidence")
    assert hits
    assert 0 < hits[0].retrieval_score <= 1
    assert hits[0].knowledge_base_hash == parsed["knowledge_base_hash"]
    assert hits[0].source_file == str(source.resolve())


def test_user_question_is_an_independent_embedding_query(tmp_path):
    source = tmp_path / "kb.md"
    source.write_text("# 规则\n## 计分\n干净且有效的击打是评判依据。\n", encoding="utf-8")
    settings = Settings(dashscope_api_key="test-key")
    retriever = RuleRetriever(source, settings=settings)
    calls = []

    def record_retrieve(query, *, domain=None, top_k=6):
        calls.append((query, domain))
        return []

    retriever.retrieve = record_retrieve
    retriever.retrieve_batch(
        ["round_scoring:10_point_must"],
        user_query="红方的有效进攻是否占优？",
    )
    assert calls == [
        ("红方的有效进攻是否占优？", None),
        ("round_scoring:10_point_must", "round_scoring"),
    ]
