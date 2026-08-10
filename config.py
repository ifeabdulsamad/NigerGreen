"""Central configuration for NaijaGreen Chat.

Values are loaded from environment variables or a local ``.env`` file.
All secrets live in the environment; nothing sensitive is hard-coded.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Config(BaseSettings):
    """Application configuration, validated at startup (pydantic-settings)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- LLM provider (DeepSeek via LiteLLM) ---
    deepseek_api_key: str = ""
    schema_model: str = "deepseek/deepseek-chat"
    sql_model: str = "deepseek/deepseek-chat"
    fallback_model: str = "deepseek/deepseek-reasoner"
    schema_max_tokens: int = 200
    sql_max_tokens: int = 500
    llm_temperature: float = 0.1
    llm_timeout_s: float = 30.0

    # --- Runtime ---
    db_path: str = "naijagreen.db"
    data_dir: str = "./data"
    upload_dir: str = ""  # defaults to <data_dir>/uploads
    demo_mode: bool = False
    log_level: str = "INFO"
    log_json: bool = True

    # --- Query safety ---
    query_timeout_ms: int = 5000
    max_retries: int = 2
    max_question_length: int = 500
    max_upload_mb: int = 20

    # --- Caching ---
    cache_enabled: bool = True
    cache_schema_ttl_s: int = 1800  # 30 min
    cache_sql_ttl_s: int = 3600  # 1 hour
    cache_result_ttl_s: int = 300  # 5 min
    cache_max_entries: int = 200

    # ------------------------------------------------------------------
    @property
    def resolved_upload_dir(self) -> Path:
        """Absolute upload sandbox directory (created on demand)."""
        base = (
            Path(self.upload_dir)
            if self.upload_dir
            else Path(self.data_dir) / "uploads"
        )
        base.mkdir(parents=True, exist_ok=True)
        return base

    @property
    def resolved_data_dir(self) -> Path:
        d = Path(self.data_dir)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def validate_config(self) -> None:
        """Fail fast on inconsistent configuration at startup."""
        if self.query_timeout_ms <= 0:
            raise ValueError("query_timeout_ms must be positive")
        if self.max_retries < 0 or self.max_retries > 5:
            raise ValueError("max_retries must be in [0, 5]")
        if not (0.0 <= self.llm_temperature <= 2.0):
            raise ValueError("llm_temperature must be in [0.0, 2.0]")
        if not self.deepseek_api_key and not self.demo_mode:
            logger.warning(
                "DEEPSEEK_API_KEY is not set and demo_mode=false — the LLM pipeline "
                "will fail with E001. Set the key or run with DEMO_MODE=true."
            )

    def masked_key(self) -> str:
        """Return a masked form of the API key for safe logging."""
        if not self.deepseek_api_key:
            return "<unset>"
        k = self.deepseek_api_key
        return f"{k[:4]}...{k[-4:]}" if len(k) > 8 else "****"


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Singleton config so Streamlit reruns don't re-parse the env file."""
    cfg = Config()
    cfg.validate_config()
    return cfg
