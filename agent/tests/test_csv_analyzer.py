from __future__ import annotations

import pandas as pd
import pytest

from boxing_judge_agent.csv_analyzer import ANNOTATION_COLUMNS, analyze_event_batch, build_views, load_and_validate_csv
from boxing_judge_agent.errors import CSVValidationError


def test_runtime_view_isolates_annotations_and_preserves_null(sample_csv):
    frame = load_and_validate_csv(sample_csv)
    runtime, offline = build_views(frame)
    assert not (set(runtime.columns) & set(ANNOTATION_COLUMNS))
    assert "contact_outcome" in offline.columns
    assert pd.isna(runtime.loc[runtime.event_id == "e2", "contact_frame"]).item()
    result = analyze_event_batch(sample_csv)
    assert result["dataset"]["event_count"] == 2
    assert result["event_index"]["e2"]["contact_frame"] is None


def test_duplicate_event_id_is_rejected(sample_csv):
    frame = pd.read_csv(sample_csv)
    frame.loc[1, "event_id"] = "e1"
    frame.to_csv(sample_csv, index=False)
    with pytest.raises(CSVValidationError) as exc:
        analyze_event_batch(sample_csv)
    assert exc.value.code == "duplicate_event_id"


def test_confidence_range_is_validated(sample_csv):
    frame = pd.read_csv(sample_csv)
    frame.loc[0, "pred_contact_outcome_confidence"] = 1.1
    frame.to_csv(sample_csv, index=False)
    with pytest.raises(CSVValidationError) as exc:
        analyze_event_batch(sample_csv)
    assert exc.value.code == "invalid_csv"

