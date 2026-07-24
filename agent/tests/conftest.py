from __future__ import annotations

import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def fake_qwen_embeddings(monkeypatch):
    """Keep unit tests offline while exercising the embedding-only retrieval path."""
    from boxing_judge_agent.rag.embedding import QwenEmbeddingClient

    def embed(self, texts):
        vectors = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for character in text:
                vector[ord(character) % self.dimensions] += 1.0
            vectors.append(vector)
        return vectors

    monkeypatch.setattr(QwenEmbeddingClient, "embed", embed)


@pytest.fixture
def sample_csv(tmp_path):
    rows = [
        {
            "event_id": "e1", "video_id": "v1", "video_name": "v1.mp4", "fighter": "red",
            "start_frame": 1, "peak_frame": 2, "contact_frame": 2, "end_frame": 3,
            "punch_type": "lead_straight", "target": "head", "contact_outcome": "landed",
            "score_result": "scored", "no_score_reason": "none", "foul_action": "", "notes": "secret",
            "pred_contact_outcome": "landed", "pred_contact_outcome_confidence": 0.8,
            "pred_punch_type": "lead_straight", "pred_punch_type_confidence": 0.9,
        },
        {
            "event_id": "e2", "video_id": "v1", "video_name": "v1.mp4", "fighter": "blue",
            "start_frame": 4, "peak_frame": 5, "contact_frame": None, "end_frame": 6,
            "punch_type": "right_hook", "target": "body", "contact_outcome": "missed",
            "score_result": "no_score", "no_score_reason": "missed", "foul_action": "", "notes": "",
            "pred_contact_outcome": "missed", "pred_contact_outcome_confidence": 0.6,
            "pred_punch_type": "right_hook", "pred_punch_type_confidence": 0.7,
        },
    ]
    path = tmp_path / "events.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path
