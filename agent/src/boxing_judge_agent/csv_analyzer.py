from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from .errors import CSVValidationError


LOCATION_COLUMNS = [
    "event_id", "video_id", "video_name", "fighter", "start_frame",
    "peak_frame", "contact_frame", "end_frame",
]
PREDICTION_COLUMNS = [
    "pred_contact_outcome", "pred_contact_outcome_confidence",
    "pred_punch_type", "pred_punch_type_confidence",
]
ANNOTATION_COLUMNS = [
    "punch_type", "target", "contact_outcome", "score_result",
    "no_score_reason", "foul_action", "notes",
]
REQUIRED_COLUMNS = LOCATION_COLUMNS + PREDICTION_COLUMNS
CONTACT_VALUES = {"landed", "blocked", "missed"}
FIGHTER_VALUES = {"red", "blue"}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _clean_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {key: _clean_value(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def load_and_validate_csv(path: str | Path) -> pd.DataFrame:
    csv_path = Path(path)
    if not csv_path.is_file():
        raise CSVValidationError("invalid_csv", f"CSV 文件不存在：{csv_path}")
    try:
        frame = pd.read_csv(csv_path)
    except Exception as exc:
        raise CSVValidationError("invalid_csv", f"无法读取 CSV：{exc}") from exc

    missing = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
    if missing:
        raise CSVValidationError(
            "missing_required_columns", f"缺少必需列：{', '.join(missing)}"
        )
    if frame["event_id"].isna().any() or (frame["event_id"].astype(str).str.strip() == "").any():
        raise CSVValidationError("invalid_csv", "event_id 不能为空")
    duplicated = frame.loc[frame["event_id"].duplicated(), "event_id"].astype(str).tolist()
    if duplicated:
        raise CSVValidationError(
            "duplicate_event_id", f"event_id 重复：{', '.join(duplicated[:5])}"
        )
    invalid_fighters = sorted(set(frame["fighter"].dropna().astype(str)) - FIGHTER_VALUES)
    if invalid_fighters:
        raise CSVValidationError("invalid_csv", f"fighter 枚举非法：{invalid_fighters}")
    invalid_contacts = sorted(
        set(frame["pred_contact_outcome"].dropna().astype(str)) - CONTACT_VALUES
    )
    if invalid_contacts:
        raise CSVValidationError(
            "invalid_csv", f"pred_contact_outcome 枚举非法：{invalid_contacts}"
        )

    for column in ["start_frame", "peak_frame", "contact_frame", "end_frame"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")
    for column in ["pred_contact_outcome_confidence", "pred_punch_type_confidence"]:
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if numeric.isna().any() or ((numeric < 0) | (numeric > 1)).any():
            raise CSVValidationError("invalid_csv", f"{column} 必须是 0 到 1 的数值")
        frame[column] = numeric
    if frame[["start_frame", "peak_frame", "end_frame"]].isna().any().any():
        raise CSVValidationError("invalid_csv", "开始、峰值和结束帧不能为空且必须为整数")
    if (frame[["start_frame", "peak_frame", "end_frame"]] < 0).any().any():
        raise CSVValidationError("invalid_csv", "帧号不能为负数")
    return frame


def build_views(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    runtime = frame[REQUIRED_COLUMNS].copy()
    offline_columns = list(dict.fromkeys(REQUIRED_COLUMNS + [c for c in ANNOTATION_COLUMNS if c in frame]))
    offline = frame[offline_columns].copy()
    if set(runtime.columns) & set(ANNOTATION_COLUMNS):
        raise AssertionError("runtime view annotation leakage")
    return runtime, offline


def _distribution(series: pd.Series) -> dict[str, int]:
    return {str(k): int(v) for k, v in series.value_counts(dropna=False).items()}


def _confidence_summary(series: pd.Series) -> dict[str, float]:
    return {
        "min": round(float(series.min()), 6),
        "median": round(float(series.median()), 6),
        "mean": round(float(series.mean()), 6),
        "max": round(float(series.max()), 6),
    }


def analyze_event_batch(
    csv_path: str | Path, mode: Literal["runtime", "offline_eval"] = "runtime"
) -> dict[str, Any]:
    """Read and deterministically analyze the entire CSV exactly once per call."""
    path = Path(csv_path).resolve()
    source_hash = file_sha256(path)
    frame = load_and_validate_csv(path)
    runtime, offline = build_views(frame)
    active = runtime if mode == "runtime" else offline

    anomalies: list[dict[str, str]] = []
    invalid_order = frame[
        ~((frame.start_frame <= frame.peak_frame) & (frame.peak_frame <= frame.end_frame))
    ]
    for event_id in invalid_order.event_id.astype(str).head(100):
        anomalies.append({"event_id": event_id, "kind": "frame_order"})
    contact_outside = frame[
        frame.contact_frame.notna()
        & ((frame.contact_frame < frame.start_frame) | (frame.contact_frame > frame.end_frame))
    ]
    for event_id in contact_outside.event_id.astype(str).head(100):
        anomalies.append({"event_id": event_id, "kind": "contact_frame_outside_event"})

    videos: list[dict[str, Any]] = []
    for video_id, group in runtime.groupby("video_id", sort=True):
        ordered = group.sort_values(["start_frame", "event_id"])
        fighters: dict[str, Any] = {}
        for fighter, subset in ordered.groupby("fighter", sort=True):
            fighters[str(fighter)] = {
                "event_count": int(len(subset)),
                "predicted_contact_distribution": _distribution(subset.pred_contact_outcome),
                "predicted_punch_type_distribution": _distribution(subset.pred_punch_type),
                "contact_confidence": _confidence_summary(subset.pred_contact_outcome_confidence),
                "punch_type_confidence": _confidence_summary(subset.pred_punch_type_confidence),
            }
        videos.append({
            "video_id": str(video_id),
            "event_count": int(len(ordered)),
            "frame_range": [int(ordered.start_frame.min()), int(ordered.end_frame.max())],
            "fighter_summaries": fighters,
            "round": None,
        })

    missing_counts = {col: int(runtime[col].isna().sum()) for col in runtime.columns}
    event_index = {str(row["event_id"]): row for row in _records(runtime)}
    signatures = sorted(
        {f"scoring_evidence:{value}:target_unknown" for value in runtime.pred_contact_outcome}
        | {"round_scoring:10_point_must", "authority:knockdown_deduction"}
    )
    return {
        "analysis_id": f"batch_{source_hash[:12]}",
        "source": {"file": str(path), "sha256": source_hash, "mode": mode},
        "dataset": {
            "event_count": int(len(active)),
            "video_count": int(runtime.video_id.nunique()),
            "gt_fields_removed": mode == "runtime",
            "round_manifest_available": False,
            "fps_available": False,
        },
        "videos": videos,
        "missing_values": missing_counts,
        "anomalies": anomalies,
        "unique_rule_query_signatures": signatures,
        "event_index": event_index,
    }


def get_event_details(batch: dict[str, Any], event_id: str) -> dict[str, Any] | None:
    event = batch.get("event_index", {}).get(event_id)
    if event is None:
        return None
    forbidden = set(event) & set(ANNOTATION_COLUMNS)
    if forbidden:
        raise AssertionError(f"annotation fields leaked: {sorted(forbidden)}")
    return event

