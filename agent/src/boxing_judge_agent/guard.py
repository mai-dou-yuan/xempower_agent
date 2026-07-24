from __future__ import annotations

from typing import Any

from .csv_analyzer import ANNOTATION_COLUMNS
from .schemas import EvidenceRef, RoundAssessment, ScoreRow, SupplementRecord


def _find_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        result = set(value)
        for child in value.values():
            result |= _find_keys(child)
        return result
    if isinstance(value, list):
        result: set[str] = set()
        for child in value:
            result |= _find_keys(child)
        return result
    return set()


def validate_output(
    batch: dict[str, Any],
    assessments: list[RoundAssessment],
    scorecard: dict[str, Any],
    evidence: list[EvidenceRef],
    supplements: list[SupplementRecord],
) -> list[str]:
    errors: list[str] = []
    if batch.get("source", {}).get("mode") != "runtime":
        errors.append("GT/标注视图不得传入运行时 Agent")
    leaked = _find_keys(batch) & set(ANNOTATION_COLUMNS)
    if leaked:
        errors.append(f"运行时标签泄漏：{sorted(leaked)}")
    evidence_ids = {x.chunk_id for x in evidence}
    for assessment in assessments:
        unknown_refs = set(assessment.evidence_refs) - evidence_ids
        if unknown_refs:
            errors.append(f"第 {assessment.round} 回合引用不存在：{sorted(unknown_refs)}")
        for metric in ("knockdowns", "deductions"):
            source = getattr(assessment, metric).get("source")
            has_values = any(isinstance(getattr(assessment, metric).get(side), int) for side in ("red", "blue"))
            if has_values and source != "verified_official_ruling":
                errors.append(f"第 {assessment.round} 回合 {metric} 缺少正式裁定来源")
    for raw in scorecard.get("rounds", []):
        row = ScoreRow.model_validate(raw)
        if row.red_adjusted is not None and row.red_adjusted != row.red_base - row.red_deduction:
            errors.append(f"第 {row.round} 回合红方算术不一致")
        if row.blue_adjusted is not None and row.blue_adjusted != row.blue_base - row.blue_deduction:
            errors.append(f"第 {row.round} 回合蓝方算术不一致")
    if any(not x.confirmed for x in supplements):
        errors.append("存在未确认的用户补充被送入最终判分")
    return errors

