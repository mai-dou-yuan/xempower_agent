from __future__ import annotations

from typing import Any


def analyze_missing_context(batch: dict[str, Any]) -> dict[str, Any]:
    dataset = batch["dataset"]
    missing: list[dict[str, Any]] = []
    if not dataset.get("round_manifest_available"):
        missing.append({
            "key": "round_mapping",
            "status": "unknown",
            "impact": "无法把各视频事件可靠归入回合，也无法形成唯一逐回合比分。",
            "question": "请提供已完成回合数，以及 video_id/帧区间到回合的映射。",
        })
    missing.extend([
        {
            "key": "effective_offense_quality",
            "status": "unknown",
            "impact": "预测命中不能单独证明合法、干净、有力且有效的进攻。",
            "question": "各回合双方的干净命中、力量、准确性和实际效果大致如何？",
        },
        {
            "key": "official_rulings",
            "status": "unknown",
            "impact": "不能自行认定击倒、犯规或正式扣分。",
            "question": "是否有台上裁判正式认定的击倒、犯规或扣分？不知道也可以回答未知。",
        },
        {
            "key": "coverage",
            "status": "unknown",
            "impact": "数据缺段可能改变回合胜负。",
            "question": "CSV/视频是否覆盖完整比赛，是否缺少重要片段？",
        },
    ])
    return {
        "items": missing,
        "choice_prompt": "请选择 add_supplement 补充信息，或 skip_supplement 按现有证据继续。",
        "questions": [x["question"] for x in missing[:3]],
    }

