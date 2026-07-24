from __future__ import annotations

import re
from typing import Any

from .schemas import SupplementRecord


ROUND_RE = re.compile(r"第\s*(\d+)\s*回合")
RANGE_RE = re.compile(r"(?:约|大约|大概)?\s*(\d+(?:\.\d+)?)\s*[—–~-]\s*(\d+(?:\.\d+)?)\s*(?:次|%)?")
PERCENT_RE = re.compile(r"(?:约|大约|大概)?\s*(\d+(?:\.\d+)?)\s*%")


def is_skip_message(text: str) -> bool:
    normalized = text.lower().strip()
    return any(token in normalized for token in [
        "skip_supplement", "跳过补充", "不补充", "直接根据", "按现有数据"
    ])


def parse_user_supplement(text: str, revision: int) -> list[SupplementRecord]:
    raw = text.strip()
    round_match = ROUND_RE.search(raw)
    round_no = int(round_match.group(1)) if round_match else None
    fighter = "red" if "红方" in raw else "blue" if "蓝方" in raw or "蓝方" in raw else None
    confidence = "low" if any(x in raw for x in ["不清楚", "不知道", "未知"]) else "medium"
    source_type = "user_estimate" if any(x in raw for x in ["大约", "大概", "约", "%", "略", "接近", "明显"]) else "user_asserted_fact"
    records: list[SupplementRecord] = []

    if "视频" in raw and ("回合" in raw or "映射" in raw):
        records.append(SupplementRecord(
            revision=revision, scope="bout", metric="round_mapping", value=raw,
            source_type=source_type, confidence=confidence, raw_user_text=raw,
        ))
    if any(x in raw for x in ["击倒", "扣分", "犯规", "警告"]):
        metric = "official_rulings"
        if "不知道" in raw or "不清楚" in raw or "未知" in raw:
            value: Any = "unknown"
        else:
            value = raw
        verified = "正式" in raw and any(x in raw for x in ["裁判", "裁定"])
        records.append(SupplementRecord(
            revision=revision, scope="round" if round_no else "bout", round=round_no,
            fighter=fighter, metric=metric, value=value,
            source_type="verified_official_ruling" if verified else source_type,
            confidence="high" if verified else confidence, raw_user_text=raw,
        ))
    if any(x in raw for x in ["命中", "进攻", "重拳", "力量", "准确", "效果", "优势", "接近"]):
        range_match = RANGE_RE.search(raw)
        percent_match = PERCENT_RE.search(raw)
        value_range = [float(range_match.group(1)), float(range_match.group(2))] if range_match else None
        value = float(percent_match.group(1)) / 100 if percent_match else raw
        records.append(SupplementRecord(
            revision=revision, scope="round" if round_no else "bout", round=round_no,
            fighter=fighter, metric="effective_offense_quality", value=value,
            value_range=value_range, source_type=source_type, confidence=confidence,
            raw_user_text=raw,
        ))
    if any(x in raw for x in ["覆盖完整", "完整比赛", "缺少", "缺失片段"]):
        records.append(SupplementRecord(
            revision=revision, metric="coverage", value=raw, source_type=source_type,
            confidence=confidence, raw_user_text=raw,
        ))
    if not records:
        records.append(SupplementRecord(
            revision=revision, metric="other_context", value=raw,
            source_type=source_type, confidence=confidence, raw_user_text=raw,
        ))
    return records


def find_conflicts(existing: list[SupplementRecord], pending: list[SupplementRecord]) -> list[dict[str, str]]:
    conflicts: list[dict[str, str]] = []
    for new in pending:
        for old in existing:
            same_key = (old.scope, old.round, old.fighter, old.metric) == (
                new.scope, new.round, new.fighter, new.metric
            )
            if same_key and old.value != new.value:
                conflicts.append({
                    "metric": new.metric,
                    "existing": str(old.value),
                    "new": str(new.value),
                })
    return conflicts


def minimal_mapping_assumption(batch: dict[str, Any], revision: int) -> SupplementRecord:
    mapping = {
        video["video_id"]: index + 1 for index, video in enumerate(batch.get("videos", []))
    }
    return SupplementRecord(
        revision=revision,
        metric="round_mapping",
        value=mapping,
        source_type="agent_assumption",
        confidence="low",
        raw_user_text="按 video_id 的排序将每个视频依次视作一个完整回合。",
        confirmed=False,
    )

