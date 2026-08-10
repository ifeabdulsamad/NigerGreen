"""Database layer tests: validation, execution, tables (TRD §10.1)."""
from __future__ import annotations

import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from database import DatabaseManager, SQLValidationError

# ----------------------------------------------------------------------
# create / list / preview
# ----------------------------------------------------------------------
def test_create_table_and_list(tmp_db):
    df = pd.DataFrame({"year": [2020, 2021], "val": [1.5, 2.5]})
    tmp_db.create_table_from_df(df, "csv_001_emissions")
    tables = tmp_db.list_tables()
    assert "csv_001_emissions" in tables
    preview = tmp_db.get_table_preview("csv_001_emissions", n=1)
    assert len(preview) == 1
    assert tmp_db.table_row_count("csv_001_emissions") == 2


def test_vacuum_runs(tmp_db):
    tmp_db.execute_raw("CREATE TABLE IF NOT EXISTS t1 (a INTEGER)")
    tmp_db.vacuum()  # must not raise


# ----------------------------------------------------------------------
# validate_sql — whitelist enforcement
# ----------------------------------------------------------------------
def test_valid_select_passes(tmp_db):
    ok, reason = tmp_db.validate_sql(
        "SELECT year, SUM(val) FROM csv_001_emissions GROUP BY year",
        "csv_001_emissions",
    )
    assert ok, reason


def test_aliased_and_quoted_table_passes(tmp_db):
    ok, reason = tmp_db.validate_sql(
        'SELECT e.year FROM "csv_001_emissions" AS e', "csv_001_emissions"
    )
    assert ok, reason


def test_subquery_and_cte_pass(tmp_db):
    ok, reason = tmp_db.validate_sql(
        "SELECT * FROM csv_001_emissions WHERE year IN "
        "(SELECT year FROM csv_001_emissions WHERE val > 1)",
        "csv_001_emissions",
    )
    assert ok, reason
    ok2, reason2 = tmp_db.validate_sql(
        "WITH y AS (SELECT year FROM csv_001_emissions) SELECT * FROM y",
        "csv_001_emissions",
    )
    assert ok2, reason2


def test_wrong_table_rejected(tmp_db):
    ok, reason = tmp_db.validate_sql(
        "SELECT * FROM csv_002_other", "csv_001_emissions"
    )
    assert not ok
    assert "csv_002_other" in reason


def test_cross_table_join_rejected(tmp_db):
    ok, _ = tmp_db.validate_sql(
        "SELECT * FROM csv_001_emissions JOIN csv_002_other ON 1=1",
        "csv_001_emissions",
    )
    assert not ok


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM csv_001_emissions",
        "UPDATE csv_001_emissions SET val=0",
        "DROP TABLE csv_001_emissions",
        "INSERT INTO csv_001_emissions VALUES (1)",
        "PRAGMA table_info(csv_001_emissions)",
        "ATTACH DATABASE 'x' AS evil",
        "SELECT * FROM sqlite_master",
        "SELECT load_extension('lib.so')",
        "SELECT * FROM csv_001_emissions; SELECT * FROM csv_001_emissions",
        "VACUUM",
    ],
)
def test_dangerous_sql_rejected(tmp_db, sql):
    ok, reason = tmp_db.validate_sql(sql, "csv_001_emissions")
    assert not ok, f"should reject: {sql!r} (got reason {reason})"


def test_execute_query_rejects_dml(tmp_db):
    with pytest.raises(SQLValidationError):
        tmp_db.execute_query("DELETE FROM whatever")


# ----------------------------------------------------------------------
# execution
# ----------------------------------------------------------------------
def test_execute_query_returns_dataframe(tmp_db):
    tmp_db.create_table_from_df(
        pd.DataFrame({"a": [1, 2, 3]}), "csv_001_x", if_exists="replace"
    )
    df = tmp_db.execute_query("SELECT SUM(a) AS s FROM csv_001_x")
    assert df.iloc[0]["s"] == 6


def test_execute_query_timeout_wrapper(tmp_db):
    # Cross-product join is big enough to blow a tiny deadline.
    tmp_db.create_table_from_df(pd.DataFrame({"a": range(2000)}), "t_a")
    tmp_db.create_table_from_df(pd.DataFrame({"b": range(2000)}), "t_b")
    with pytest.raises(Exception):
        tmp_db.execute_query(
            "SELECT count(*) FROM t_a, t_b WHERE t_a.a != t_b.b", timeout_ms=1
        )


# ----------------------------------------------------------------------
# property-based fuzz (TRD §10.1: no false-positives on dangerous SQL)
# ----------------------------------------------------------------------
DANGER = ["PRAGMA", "ATTACH", "DROP", "DELETE", "INSERT", "UPDATE"]


@given(
    st.lists(st.sampled_from(DANGER), min_size=1, max_size=3),
    st.text(alphabet="abc 123,()*=", max_size=20),
)
@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_fuzz_dangerous_fragments_never_validate(tmp_db, fragments, filler):
    sql = "SELECT " + " ".join(fragments) + " " + filler
    ok, _ = tmp_db.validate_sql(sql, "csv_001_emissions")
    assert not ok


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; SELECT 2",                      # two statements
        "SELECT 1;-- comment",                     # trailing injection
        "SELECT * FROM csv_001_emissions; DROP TABLE csv_001_emissions",
    ],
)
def test_semicolon_injection_rejected(tmp_db, sql):
    ok, _ = tmp_db.validate_sql(sql, "csv_001_emissions")
    assert not ok


@given(st.text(alphabet="yearval 1234,()*=", max_size=40))
@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_fuzz_benign_selects_validate(tmp_db, filler):
    sql = "SELECT * FROM csv_001_emissions WHERE " + filler
    ok, _ = tmp_db.validate_sql(sql, "csv_001_emissions")
    assert ok
