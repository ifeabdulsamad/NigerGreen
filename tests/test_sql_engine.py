"""SQL engine tests: full pipeline, demo rules, error taxonomy (TRD §10.2)."""
from __future__ import annotations

import pandas as pd
import pytest

from sql_engine import InputValidationError, SchemaSelectionError
from tests.conftest import FIXTURES


def test_end_to_end_with_mocked_llm(emissions_engine):
    result = emissions_engine.answer_question(
        "total co2 per year in lagos"
    )
    assert result["error"] is None, result["error"]
    assert result["selected_table"] == emissions_engine.table_name
    assert "GROUP BY year" in result["sql"]
    assert isinstance(result["results"], pd.DataFrame)
    assert len(result["results"]) == 5  # 2018..2022
    assert result["cached"] is False
    assert result["execution_time_ms"] >= 0
    assert result["nl_summary"]


def test_result_caching_second_call_hits(emissions_engine):
    emissions_engine.answer_question("total co2 per year in lagos")
    calls = {"n": 0}
    original = emissions_engine._call_llm

    def counting(prompt, stage, relax_on_error=False):
        calls["n"] += 1
        return original(prompt, stage, relax_on_error)

    emissions_engine._call_llm = counting  # type: ignore[method-assign]
    result = emissions_engine.answer_question("total co2 per year in lagos")
    assert result["cached"] is True
    assert calls["n"] == 0  # LLM never called again


def test_unsafe_sql_returns_e004(emissions_engine):
    def evil(prompt, stage, relax_on_error=False):
        if stage == "schema":
            return f"<{emissions_engine.tid}>"
        return "DELETE FROM whatever"

    emissions_engine._call_llm = evil  # type: ignore[method-assign]
    result = emissions_engine.answer_question("delete everything")
    assert result["error"] is not None
    assert "E004" in result["error"]


def test_cannot_answer_returns_friendly_message(emissions_engine):
    def refuses(prompt, stage, relax_on_error=False):
        if stage == "schema":
            return f"<{emissions_engine.tid}>"
        return "SELECT 'CANNOT_ANSWER' AS error;"

    emissions_engine._call_llm = refuses  # type: ignore[method-assign]
    result = emissions_engine.answer_question("what is the meaning of life")
    assert result["error"] is not None
    assert "No relevant data found" in result["error"]


def test_question_too_long_rejected(emissions_engine):
    with pytest.raises(InputValidationError):
        emissions_engine.answer_question("x" * 501)


def test_empty_question_rejected(emissions_engine):
    with pytest.raises(InputValidationError):
        emissions_engine.answer_question("   ")


def test_no_datasets_returns_clean_error(engine):
    result = engine.answer_question("anything")
    assert "error" in result and "No datasets" in result["error"]


# ----------------------------------------------------------------------
# Demo mode (no API key, rule-based) — TRD §7.3
# ----------------------------------------------------------------------
@pytest.fixture()
def demo_with_data(demo_engine):
    demo_engine.registry.register_csv(str(FIXTURES / "emissions_lagos.csv"))
    demo_engine.registry.register_csv(str(FIXTURES / "energy_national.csv"))
    return demo_engine


def test_demo_mode_answers_total_per_year(demo_with_data):
    result = demo_with_data.answer_question("total co2 emissions per year")
    assert result["error"] is None, result["error"]
    assert "SUM" in result["sql"].upper()
    assert "GROUP BY" in result["sql"].upper()
    assert isinstance(result["results"], pd.DataFrame)
    assert len(result["results"]) == 5


def test_demo_mode_answers_average(demo_with_data):
    result = demo_with_data.answer_question("average co2 emissions")
    assert result["error"] is None, result["error"]
    assert "AVG" in result["sql"].upper()


def test_demo_mode_schema_selection_picks_energy(demo_with_data):
    # energy question must select the energy table, not emissions
    tid = demo_with_data.select_schema(
        "which state has the highest renewable share",
        demo_with_data.registry.get_all_schemas(),
    )
    meta = demo_with_data.registry.get_meta(tid)
    assert "energy" in meta["table_name"]


def test_demo_mode_honors_cache_disabled(demo_with_data):
    demo_with_data.answer_question("total co2 emissions per year")
    result = demo_with_data.answer_question("total co2 emissions per year")
    assert result["cached"] is False
