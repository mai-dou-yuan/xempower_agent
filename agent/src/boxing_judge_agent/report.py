from __future__ import annotations

from typing import Any

from .schemas import AgentSession


DISCLAIMER = "本报告仅为基于现有证据的分析意见，不是官方赛果或正式记分卡。"


def _fighter_summary(batch: dict[str, Any], fighter: str) -> str:
    parts = []
    for video in batch.get("videos", []):
        summary = video.get("fighter_summaries", {}).get(fighter)
        if summary:
            parts.append(
                f"{video['video_id']}：{summary['event_count']} 次预测事件，"
                f"接触预测分布 {summary['predicted_contact_distribution']}。"
            )
    return "\n\n".join(parts) or "无可用预测事件。"


def build_report(session: AgentSession, *, guard_errors: list[str] | None = None) -> dict[str, Any]:
    batch = session.batch_analysis or {}
    assessments = session.round_assessments
    scorecard = session.report.get("scorecard", {}) if session.report else {}
    swing_rounds = [x.round for x in assessments if x.confidence == "low" or x.winner in {"even", "insufficient"}]
    evidence_lines = [
        f"- `{x.chunk_id}`｜{' > '.join(x.heading_path)}｜`{x.source_file}`｜SHA-256 `{x.knowledge_base_hash}`"
        for x in session.rule_evidence
    ] or ["- 未检索到充分规则证据。"]
    supplement_lines = [
        f"- r{x.revision} `{x.source_type}` / `{x.metric}`：{x.value}（已确认）"
        for x in session.supplements if x.confirmed
    ]
    if session.supplement_mode == "skip":
        supplement_lines.insert(0, "- 用户选择跳过事实补充；未提供项保持 unknown。")
    assumption_lines = [f"- {x.raw_user_text}（{'已确认' if x.confirmed else '未采纳'}）" for x in session.assumptions]
    round_lines = [
        f"- 第 {x.round} 回合：`{x.winner}` / `{x.dominance}` / 置信度 `{x.confidence}`。{x.reason}"
        for x in assessments
    ] or ["- 缺少可靠回合映射或 LLM 定性结果，无法形成逐回合主估算。"]
    score_lines = []
    for row in scorecard.get("rounds", []):
        score_lines.append(
            f"| {row['round']} | {row['red_base']} | {row['blue_base']} | {row['red_deduction']} | "
            f"{row['blue_deduction']} | {row['red_adjusted']} | {row['blue_adjusted']} |"
        )
    score_table = "|回合|红基础|蓝基础|红扣分|蓝扣分|红调整|蓝调整|\n|---:|---:|---:|---:|---:|---:|---:|\n" + "\n".join(score_lines) if score_lines else "暂无可计算记分行。"
    total = (
        f"红方 {scorecard.get('red_total')} – 蓝方 {scorecard.get('blue_total')}"
        if scorecard.get("complete") else "总分未确定（未知项未按 0 处理）。"
    )
    status = "estimated" if scorecard.get("complete") else ("conditional" if assessments else "insufficient")
    limitations = [x["impact"] for x in (session.missing_context or {}).get("items", [])]
    if session.last_error:
        limitations.append(f"模型服务异常：{session.last_error.get('message')}")
    if guard_errors:
        limitations.extend(f"Guard：{x}" for x in guard_errors)
    plausible = session.report.get("plausible_range", {}) if session.report else {}
    alternatives = [
        "若回合映射变化，各回合统计和主比分均需重算。",
        "若存在经正式确认的击倒或扣分，基础分与调整后分可能改变。",
        "若干净程度、力量或效果证据与预测数量趋势相反，回合胜负可能翻转。",
    ]
    markdown = f"""# 拳击对战分析报告

## 1. 结论摘要与非官方声明

{DISCLAIMER} 当前状态：`{status}`；{total}

## 2. 数据范围和比赛结构

分析 `{batch.get('dataset', {}).get('event_count', 0)}` 条事件、`{batch.get('dataset', {}).get('video_count', 0)}` 个视频。回合映射可用：`{batch.get('dataset', {}).get('round_manifest_available', False)}`。

## 3. 数据质量、缺失项和模型预测局限

{chr(10).join('- ' + x for x in limitations) if limitations else '- 未发现已知缺失。'}

## 4. 用户补充信息与系统假设

{chr(10).join(supplement_lines + assumption_lines) or '- 无已确认补充或假设。'}

## 5. 红方整体表现

{_fighter_summary(batch, 'red')}

## 6. 蓝方整体表现

{_fighter_summary(batch, 'blue')}

## 7. 逐回合分析

{chr(10).join(round_lines)}

## 8. 估算记分卡

{score_table}

总计：{total}。`score_kind=estimated_opinion`，`official=false`。

## 9. 比分合理性说明

基础回合分来自结构化定性判断；正式且已确认的扣分才单独相减。预测出拳次数没有机械换算为分数。

## 10. 关键事件、摇摆回合与比赛转折

摇摆或证据不足回合：{swing_rounds or '无可识别回合'}。当前 CSV 不足以自行认定官方关键事件。

## 11. 合理比分范围与替代情景

合理范围：`{plausible}`。
{chr(10).join('- ' + x for x in alternatives)}

## 12. 规则证据索引

{chr(10).join(evidence_lines)}

## 13. 待复核事项与结论局限

{chr(10).join('- ' + x for x in limitations) if limitations else '- 仍应以赛事官方裁定为准。'}

> {DISCLAIMER}
"""
    return {
        "session_id": session.session_id,
        "analysis_id": session.analysis_id,
        "status": status,
        "score_status": status,
        "score_kind": "estimated_opinion",
        "official": False,
        "data_quality": {"missing": limitations, "anomalies": batch.get("anomalies", [])},
        "supplement_mode": session.supplement_mode,
        "assumptions": [x.model_dump(mode="json") for x in session.assumptions],
        "round_assessments": [x.model_dump(mode="json") for x in assessments],
        "scorecard": scorecard,
        "plausible_range": plausible,
        "swing_rounds": swing_rounds,
        "alternative_scenarios": alternatives,
        "rule_evidence": [x.model_dump(mode="json") for x in session.rule_evidence],
        "guard_errors": guard_errors or [],
        "report_markdown": markdown,
    }
