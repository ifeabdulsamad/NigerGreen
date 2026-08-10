"""Config tests: DeepSeek provider defaults (guard against provider regressions)."""
from __future__ import annotations

import pytest

from config import Config

RELEVANT_ENV = (
    "DEEPSEEK_API_KEY",
    "SCHEMA_MODEL",
    "SQL_MODEL",
    "FALLBACK_MODEL",
    "DEMO_MODE",
)


@pytest.fixture()
def clean_config(monkeypatch):
    """Config with no .env file and no provider env vars (hermetic defaults)."""
    for name in RELEVANT_ENV:
        monkeypatch.delenv(name, raising=False)
    return Config(_env_file=None)


def test_deepseek_model_defaults(clean_config):
    assert clean_config.schema_model == "deepseek/deepseek-chat"
    assert clean_config.sql_model == "deepseek/deepseek-chat"
    assert clean_config.fallback_model == "deepseek/deepseek-reasoner"


def test_api_key_field_is_deepseek(clean_config):
    assert clean_config.deepseek_api_key == ""
    assert clean_config.masked_key() == "<unset>"


def test_validate_config_passes_without_key_in_demo_mode(clean_config):
    clean_config.demo_mode = True
    clean_config.validate_config()  # must not raise
