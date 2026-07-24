from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_DIR / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    deepseek_api_key: str | None = Field(default=None, repr=False)
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    dashscope_api_key: str | None = Field(default=None, repr=False)
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_embedding_model: str = "qwen3.7-text-embedding"
    dashscope_embedding_dimensions: int = 1024
    dashscope_timeout_seconds: float = 60.0
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 1
    boxing_artifact_dir: Path = Path("artifacts")
    boxing_knowledge_base: Path = Path(
        "rag/knowledge_base/Ring-Official-Guidelines-Boxing-Judge-RAG.md"
    )

    @property
    def artifact_dir(self) -> Path:
        p = self.boxing_artifact_dir
        return p if p.is_absolute() else PROJECT_DIR / p

    @property
    def knowledge_base(self) -> Path:
        p = self.boxing_knowledge_base
        return p if p.is_absolute() else PROJECT_DIR / p


@lru_cache
def get_settings() -> Settings:
    return Settings()
