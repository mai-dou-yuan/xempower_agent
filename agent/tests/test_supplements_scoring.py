from __future__ import annotations

from boxing_judge_agent.schemas import RoundAssessment
from boxing_judge_agent.scoring import calculate_scorecard
from boxing_judge_agent.supplements import is_skip_message, parse_user_supplement


def test_supplement_parses_estimate_unknown_and_skip():
    records = parse_user_supplement("第 2 回合红方高质量命中约 60%，击倒情况不清楚。", 1)
    assert any(x.metric == "effective_offense_quality" and x.source_type == "user_estimate" for x in records)
    assert any(x.metric == "official_rulings" and x.value == "unknown" for x in records)
    assert is_skip_message("我不补充额外信息，请直接根据现有数据分析")


def test_deterministic_score_separates_base_and_deduction():
    assessments = [RoundAssessment(
        round=1, winner="red", dominance="close",
        deductions={"red": 1, "blue": 0, "source": "verified_official_ruling"},
        reason="红方有效进攻略优", evidence_refs=["c1"],
    )]
    card = calculate_scorecard(assessments)
    row = card["rounds"][0]
    assert (row["red_base"], row["blue_base"]) == (10, 9)
    assert (row["red_adjusted"], row["blue_adjusted"]) == (9, 9)
    assert (card["red_total"], card["blue_total"]) == (9, 9)


def test_unknown_deduction_is_not_silently_zero():
    card = calculate_scorecard([RoundAssessment(
        round=1, winner="red", dominance="close", reason="条件判断"
    )])
    assert card["rounds"][0]["red_deduction"] is None
    assert card["red_total"] is None

