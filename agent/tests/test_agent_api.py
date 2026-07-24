from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from boxing_judge_agent.agent import BoxingJudgeAgent
from boxing_judge_agent.api import app
from boxing_judge_agent.config import Settings
from boxing_judge_agent.schemas import RoundAssessment, SessionStatus


class FakeJudge:
    def __init__(self):
        self.analysis_question = None

    def assess(self, round_contexts, supplements, evidence, analysis_question=None):
        self.analysis_question = analysis_question
        ref = evidence[0].chunk_id
        return [RoundAssessment(
            round=x["round"], winner="red", dominance="close",
            deductions={"red": 0, "blue": 0, "source": "verified_official_ruling"},
            knockdowns={"red": 0, "blue": 0, "source": "verified_official_ruling"},
            reason="已确认的定性信息支持红方略优。", evidence_refs=[ref],
            data_sources=["user_asserted_fact"], confidence="medium",
        ) for x in round_contexts]


def _settings(tmp_path):
    project = __import__("boxing_judge_agent.config", fromlist=["PROJECT_DIR"]).PROJECT_DIR
    return Settings(
        boxing_artifact_dir=tmp_path / "artifacts",
        boxing_knowledge_base=project / "rag/knowledge_base/Ring-Official-Guidelines-Boxing-Judge-RAG.md",
        dashscope_api_key="test-key",
    )


def test_skip_branch_stops_questions_and_builds_full_report(sample_csv, tmp_path):
    agent = BoxingJudgeAgent(_settings(tmp_path), judge=FakeJudge())
    session = agent.create_session(sample_csv)
    assert session.status == SessionStatus.AWAITING_SUPPLEMENT_CHOICE
    agent.confirm(session.session_id, "skip_supplement")
    result = agent.confirm(session.session_id, "reject_assumptions")
    report = result["session"]["report"]
    assert report["status"] == "insufficient"
    assert report["official"] is False
    assert report["supplement_mode"] == "skip"
    for section in range(1, 14):
        assert f"## {section}." in report["report_markdown"]


def test_confirmed_mapping_calls_judge_and_persists(sample_csv, tmp_path):
    judge = FakeJudge()
    agent = BoxingJudgeAgent(_settings(tmp_path), judge=judge)
    session = agent.create_session(sample_csv, "重点判断红方的有效进攻是否占优")
    agent.confirm(session.session_id, "skip_supplement")
    agent.confirm(session.session_id, "confirm_assumptions")
    restored = agent.get_session(session.session_id)
    assert restored.status == SessionStatus.COMPLETE
    assert restored.report["scorecard"]["red_total"] == 10
    assert restored.report["score_kind"] == "estimated_opinion"
    assert judge.analysis_question == "重点判断红方的有效进攻是否占优"


def test_analysis_question_is_normalized_and_limited(sample_csv, tmp_path):
    agent = BoxingJudgeAgent(_settings(tmp_path), judge=FakeJudge())
    session = agent.create_session(sample_csv, "  分析第四回合  ")
    assert session.question == "分析第四回合"
    with pytest.raises(Exception) as exc_info:
        agent.create_session(sample_csv, "问" * 2001)
    assert getattr(exc_info.value, "code", None) == "invalid_question"


def test_confirmed_supplement_is_kept_when_user_finishes_input(sample_csv, tmp_path):
    agent = BoxingJudgeAgent(_settings(tmp_path), judge=FakeJudge())
    session = agent.create_session(sample_csv)
    agent.confirm(session.session_id, "add_supplement")
    agent.add_message(session.session_id, "红方在四个回合的拳击力量更强、干净命中更多")
    result = agent.confirm(session.session_id, "confirm_supplements")
    assert result["session"]["status"] == SessionStatus.AWAITING_USER_INPUT
    assert len(result["session"]["supplements"]) == 1
    assert result["session"]["supplements"][0]["confirmed"] is True

    finished = agent.confirm(session.session_id, "skip_supplement")
    assert finished["session"]["supplement_mode"] == "add"
    assert len(finished["session"]["supplements"]) == 1
    assert finished["confirmation_scope"] == "minimal_assumption"


def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_frontend_and_assets_are_served():
    client = TestClient(app)
    page = client.get("/")
    assert page.status_code == 200
    assert "CornerSight" in page.text
    assert 'href="/assets/app.css"' in page.text
    assert client.get("/assets/app.css").status_code == 200
    assert client.get("/assets/app.js").status_code == 200


def test_progress_trace_records_tools_and_is_available_from_api(sample_csv, tmp_path, monkeypatch):
    agent = BoxingJudgeAgent(_settings(tmp_path), judge=FakeJudge())
    session = agent.create_session(sample_csv, "分析有效进攻")
    agent.confirm(session.session_id, "skip_supplement")
    result = agent.confirm(session.session_id, "confirm_assumptions")
    events = result["session"]["progress_events"]
    completed_phases = {event["phase"] for event in events if event["status"] == "completed"}
    assert {
        "csv_analysis", "rule_retrieval", "llm_assessment",
        "deterministic_scoring", "guard_validation", "report_generation",
    } <= completed_phases
    assert any("Qwen" in event["tool"] for event in events)
    assert any("DeepSeek" in event["tool"] for event in events)

    monkeypatch.setattr("boxing_judge_agent.api.service", lambda: agent)
    response = TestClient(app).get(f"/sessions/{session.session_id}/progress")
    assert response.status_code == 200
    payload = response.json()
    assert payload["finished"] is True
    assert payload["progress"][-1]["phase"] == "report_generation"
    assert payload["progress"][-1]["status"] == "completed"
