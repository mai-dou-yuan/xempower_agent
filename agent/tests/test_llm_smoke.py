from __future__ import annotations

import os

import pytest

from boxing_judge_agent.config import Settings
from boxing_judge_agent.llm import DeepSeekJudge


@pytest.mark.skipif(os.getenv("RUN_DEEPSEEK_SMOKE") != "1", reason="显式启用才消耗 API 配额")
def test_deepseek_smoke():
    settings = Settings()
    assert settings.deepseek_api_key
    # Smoke only checks that a malformed/empty evidence request is handled by the live endpoint.
    result = DeepSeekJudge(settings).assess([], [], [], analysis_question="按证据分析比赛")
    assert result == []
