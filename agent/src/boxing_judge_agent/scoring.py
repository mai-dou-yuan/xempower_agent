from __future__ import annotations

from typing import Any

from .schemas import RoundAssessment, ScoreRow


def _base_score(assessment: RoundAssessment) -> tuple[int, int] | None:
    if assessment.winner == "insufficient":
        return None
    if assessment.winner == "even":
        return (10, 10)
    loser_score = {"close": 9, "clear": 8, "overwhelming": 7}[assessment.dominance]
    return (10, loser_score) if assessment.winner == "red" else (loser_score, 10)


def calculate_scorecard(assessments: list[RoundAssessment]) -> dict[str, Any]:
    rows: list[ScoreRow] = []
    for item in sorted(assessments, key=lambda x: x.round):
        base = _base_score(item)
        if base is None:
            rows.append(ScoreRow(
                round=item.round, red_base=None, blue_base=None,
                red_deduction=None, blue_deduction=None,
                red_adjusted=None, blue_adjusted=None,
            ))
            continue
        red_deduction = item.deductions.get("red")
        blue_deduction = item.deductions.get("blue")
        red_deduction = red_deduction if isinstance(red_deduction, int) else None
        blue_deduction = blue_deduction if isinstance(blue_deduction, int) else None
        rows.append(ScoreRow(
            round=item.round,
            red_base=base[0], blue_base=base[1],
            red_deduction=red_deduction, blue_deduction=blue_deduction,
            red_adjusted=base[0] - red_deduction if red_deduction is not None else None,
            blue_adjusted=base[1] - blue_deduction if blue_deduction is not None else None,
        ))
    complete = bool(rows) and all(r.red_adjusted is not None and r.blue_adjusted is not None for r in rows)
    return {
        "rounds": [row.model_dump() for row in rows],
        "red_total": sum(r.red_adjusted for r in rows if r.red_adjusted is not None) if complete else None,
        "blue_total": sum(r.blue_adjusted for r in rows if r.blue_adjusted is not None) if complete else None,
        "complete": complete,
    }


def plausible_score_range(scorecard: dict[str, Any], swing_rounds: list[int]) -> dict[str, Any]:
    if not scorecard["complete"]:
        return {"red": None, "blue": None, "reason": "存在无法确定的回合或扣分。"}
    margin = len(swing_rounds)
    return {
        "red": [scorecard["red_total"] - margin, scorecard["red_total"] + margin],
        "blue": [scorecard["blue_total"] - margin, scorecard["blue_total"] + margin],
        "reason": "每个摇摆回合按改变一分方向估算敏感区间。",
    }
