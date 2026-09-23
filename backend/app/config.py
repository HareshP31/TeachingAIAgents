from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_mode: Literal["fake", "test", "local", "live"] = "fake"
    log_level: str = "INFO"
    database_url: str = "postgresql://postgres:postgres@postgres:5432/teaching_ai_agents"
    lm_studio_base_url: str = "http://host.docker.internal:1234/v1"
    lm_studio_model: str = "qwen2.5-7b-instruct"
    lm_studio_api_key: str = "lm-studio"
    nanobot_url: str = "http://nanobot:8090"
    nanobot_timeout_seconds: float = 90
    slack_enabled: bool = False
    slack_bot_token: str | None = None
    slack_app_token: str | None = None
    risk_threshold: int = Field(default=50, ge=0, le=100)
    materiality_threshold: float = Field(default=10_000_000, gt=0)
    max_revisions: int = Field(default=2, ge=1, le=5)
    embedding_model: str = "BAAI/bge-large-en-v1.5"
    embedding_dimensions: int = 1024
    retrieval_limit: int = Field(default=12, ge=1, le=20)
    frontend_origin: str = "http://localhost:3000"
    document_store: Path = Path("/data/documents")
    guidebook_dir: Path = Path("/data/guidebooks")

    def validate_live(self) -> list[str]:
        problems: list[str] = []
        if self.app_mode in {"local", "live"} and "27b" in self.lm_studio_model.lower():
            problems.append("27B models are disabled on this 32 GB deployment")
        if self.app_mode == "live" and self.slack_enabled:
            if not self.slack_bot_token or self.slack_bot_token.startswith("xoxb-") and self.slack_bot_token.endswith("..."):
                problems.append("SLACK_BOT_TOKEN is missing")
            if not self.slack_app_token or self.slack_app_token.startswith("xapp-") and self.slack_app_token.endswith("..."):
                problems.append("SLACK_APP_TOKEN is missing")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
