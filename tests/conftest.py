"""Shared pytest fixtures (TRD §10.2: mocked LLM integration tests)."""
from __future__ import annotations

from pathlib import Path

import pytest

from config import Config
from database import DatabaseManager
from cache_manager import CacheManager
from schema_registry import SchemaRegistry
from sql_engine import TextToSQLEngine

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def tmp_db(tmp_path):
    db = DatabaseManager(str(tmp_path / "test.db"), wal_mode=True, timeout_ms=2000)
    yield db
    db.close()


@pytest.fixture()
def registry(tmp_db, tmp_path):
    return SchemaRegistry(tmp_db, data_dir=str(tmp_path / "data"))


@pytest.fixture()
def engine(tmp_db, registry, tmp_path):
    cfg = Config(
        deepseek_api_key="test-key-not-real",
        db_path=str(tmp_db.db_path),
        data_dir=str(tmp_path / "data"),
        demo_mode=False,
        log_json=False,
        cache_enabled=True,
    )
    cache = CacheManager(enabled=True, result_ttl_s=60, max_entries=50)
    return TextToSQLEngine(cfg, registry, cache)


@pytest.fixture()
def demo_engine(tmp_db, registry, tmp_path):
    cfg = Config(
        deepseek_api_key="",
        db_path=str(tmp_db.db_path),
        data_dir=str(tmp_path / "data"),
        demo_mode=True,
        log_json=False,
        cache_enabled=False,
    )
    cache = CacheManager(enabled=False)
    return TextToSQLEngine(cfg, registry, cache)


@pytest.fixture()
def emissions_engine(engine, tmp_path):
    """Engine with the emissions CSV registered and LLM mocked."""
    tid = engine.registry.register_csv(str(FIXTURES / "emissions_lagos.csv"))
    table_name = engine.registry.get_table_name(tid)

    def fake_call(prompt, stage, relax_on_error=False):
        if stage == "schema":
            return f"<{tid}>"
        return (
            "SELECT year, SUM(co2_emissions_tons) AS total_co2 "
            f"FROM {table_name} GROUP BY year ORDER BY year;"
        )

    engine._call_llm = fake_call  # type: ignore[method-assign]
    engine.tid = tid  # type: ignore[attr-defined]
    engine.table_name = table_name  # type: ignore[attr-defined]
    return engine
