"""Schema registry tests: inference, versioning, validation, search."""
from __future__ import annotations

import pytest

from schema_registry import CSVValidationError
from tests.conftest import FIXTURES


def test_register_csv_happy_path(registry):
    tid = registry.register_csv(str(FIXTURES / "emissions_lagos.csv"))
    assert tid == "001"
    meta = registry.get_meta(tid)
    assert meta["table_name"].startswith("csv_001_")
    assert meta["row_count"] == 20
    assert meta["column_count"] == 3
    assert meta["version"] == 1
    assert "TABLE:" in meta["schema_doc"]
    assert meta["table_name"] in registry.get_table_name(tid)
    assert meta["table_name"] in registry.list_tables()


def test_schema_doc_mentions_columns_and_notes(registry):
    tid = registry.register_csv(str(FIXTURES / "emissions_lagos.csv"))
    doc = registry.get_schema_doc(tid)
    assert "co2_emissions_tons" in doc
    assert "year" in doc


def test_update_csv_bumps_version(registry):
    tid = registry.register_csv(str(FIXTURES / "emissions_lagos.csv"))
    tid2 = registry.update_csv(tid, str(FIXTURES / "energy_national.csv"))
    assert tid2 == tid
    meta = registry.get_meta(tid)
    assert meta["version"] == 2
    assert meta["file_name"] == "energy_national.csv"


def test_register_second_table_gets_next_id(registry):
    registry.register_csv(str(FIXTURES / "emissions_lagos.csv"))
    tid2 = registry.register_csv(str(FIXTURES / "energy_national.csv"))
    assert tid2 == "002"


def test_delete_schema(registry):
    tid = registry.register_csv(str(FIXTURES / "emissions_lagos.csv"))
    assert registry.delete_schema(tid) is True
    assert registry.get_meta(tid) is None
    assert registry.delete_schema(tid) is False


def test_validate_csv_rejects_bad_files(registry):
    assert registry.validate_csv(str(FIXTURES / "empty.csv"))[0] is False
    assert registry.validate_csv(str(FIXTURES / "no_header.csv"))[0] is False


def test_validate_csv_rejects_wrong_extension(registry, tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("hello")
    ok, reason = registry.validate_csv(str(bad))
    assert not ok and ".csv" in reason


def test_register_rejects_invalid_csv(registry):
    with pytest.raises(CSVValidationError):
        registry.register_csv(str(FIXTURES / "empty.csv"))


def test_latin1_csv_is_detected(registry):
    ok, reason = registry.validate_csv(str(FIXTURES / "encoding_iso8859.csv"))
    assert ok, reason
    tid = registry.register_csv(str(FIXTURES / "encoding_iso8859.csv"))
    meta = registry.get_meta(tid)
    assert meta["row_count"] == 3


def test_duplicate_columns_rejected(registry, tmp_path):
    dup = tmp_path / "dup.csv"
    dup.write_text("a,a,b\n1,2,3\n")
    ok, reason = registry.validate_csv(str(dup))
    assert not ok and "Duplicate" in reason


def test_search_schemas_ranks_emissions_for_co2(registry):
    registry.register_csv(str(FIXTURES / "emissions_lagos.csv"))
    registry.register_csv(str(FIXTURES / "energy_national.csv"))
    registry.register_csv(str(FIXTURES / "water_quality_kano.csv"))
    results = registry.search_schemas("how much co2 did lagos emit", top_k=3)
    assert results, "search returned nothing"
    assert results[0][0] == "001"  # emissions table ranks first


def test_search_returns_nothing_without_tables(registry):
    assert registry.search_schemas("anything") == []
