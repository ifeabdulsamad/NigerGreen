"""Database layer: SQLite with WAL mode, AST-based SQL validation, timeouts.

Security model (TRD §8.1):
  * only single SELECT/WITH statements are allowed
  * table references are whitelisted against the registry
  * forbidden constructs (PRAGMA, ATTACH, DETACH, DML...) are rejected
  * a progress-handler deadline kills runaway queries
"""
from __future__ import annotations

import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, List, Optional, Tuple

import pandas as pd
import sqlparse
from sqlparse.sql import Identifier, IdentifierList
from sqlparse.tokens import Comment, Keyword, Name, Whitespace

logger = None  # set below to avoid import cycle at module load
try:
    from logger import get_logger

    logger = get_logger("database")
except Exception:  # pragma: no cover - import cycle guard
    pass


class SQLValidationError(ValueError):
    """Raised when SQL fails the safety validation."""


# Statements that can never be run through the engine.
FORBIDDEN_KEYWORDS = (
    "PRAGMA", "ATTACH", "DETACH", "VACUUM", "REINDEX", "SAVEPOINT",
    "RELEASE", "BEGIN", "COMMIT", "ROLLBACK", "CREATE", "DROP", "ALTER",
    "INSERT", "UPDATE", "DELETE", "REPLACE", "GRANT", "REVOKE",
)
FORBIDDEN_FRAGMENTS = (
    "sqlite_master", "sqlite_temp_master", "load_extension",
    "readfile", "writefile", "system",
)
DANGEROUS_PATTERN = re.compile(
    r"(\bPRAGMA\b|\bATTACH\b|\bDETACH\b|\bVACUUM\b|"
    r"load_extension|sqlite_|\bDROP\b|\bINSERT\b|\bUPDATE\b|\bDELETE\b|\bALTER\b)",
    re.IGNORECASE,
)


class DatabaseManager:
    """Owns the SQLite connection; all access goes through it."""

    def __init__(
        self,
        db_path: str = "naijagreen.db",
        wal_mode: bool = True,
        timeout_ms: int = 5000,
    ) -> None:
        parent = str(Path(db_path).parent)
        if parent and parent != ".":
            Path(parent).mkdir(parents=True, exist_ok=True)

        self.db_path = str(db_path)
        self.timeout_ms = timeout_ms
        self._lock = threading.RLock()
        self._deadline: Optional[float] = None

        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        if wal_mode:
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        # Progress handler: sqlite calls back every ~100k VM instructions;
        # we translate that into a wall-clock deadline check.
        self._conn.set_progress_handler(self._progress_check, 100_000)

    # ------------------------------------------------------------------
    # Timeout enforcement
    # ------------------------------------------------------------------
    def _progress_check(self) -> int:
        if self._deadline is not None and time.monotonic() > self._deadline:
            raise sqlite3.OperationalError(
                f"Query timeout exceeded ({self.timeout_ms}ms)"
            )
        return 0

    # ------------------------------------------------------------------
    # Schema / table management
    # ------------------------------------------------------------------
    def create_table_from_df(
        self, df: pd.DataFrame, table_name: str, if_exists: str = "replace"
    ) -> None:
        if if_exists not in ("replace", "fail", "append"):
            raise ValueError(f"if_exists must be replace|fail|append, got {if_exists}")
        with self._lock:
            df.to_sql(table_name, self._conn, if_exists=if_exists, index=False)

    def list_tables(self) -> List[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        return [r["name"] for r in rows]

    def get_table_preview(self, table_name: str, n: int = 5) -> pd.DataFrame:
        with self._lock:
            return pd.read_sql_query(
                f"SELECT * FROM {table_name} LIMIT {int(n)}", self._conn
            )

    def table_row_count(self, table_name: str) -> int:
        with self._lock:
            row = self._conn.execute(
                f"SELECT COUNT(*) AS c FROM {table_name}"
            ).fetchone()
        return int(row["c"])

    def vacuum(self) -> None:
        with self._lock:
            self._conn.execute("VACUUM")

    def execute_raw(self, sql: str, params: Tuple[Any, ...] = ()) -> None:
        """Admin helper for internal DDL/DML (registry tables only)."""
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    # ------------------------------------------------------------------
    # SQL validation (AST-aware via sqlparse)
    # ------------------------------------------------------------------
    @staticmethod
    def _skippable(tok: Any) -> bool:
        """Whitespace/comments (handles sqlparse versions that lack is_comment)."""
        if getattr(tok, "is_whitespace", False):
            return True
        ttype = getattr(tok, "ttype", None)
        return ttype is not None and ttype in (Comment, Whitespace)

    @staticmethod
    def _extract_table_names(parsed: Any) -> set:
        """Pull table identifiers that follow FROM/JOIN keywords.

        Works on the flattened token stream (leaf tokens), which handles
        subqueries naturally: every nested FROM/JOIN appears in the stream.
        CTE names are collected separately by the caller and subtracted.
        """
        tables: set = set()

        def table_of(ident: Any) -> str:
            # Identifier groups expose get_real_name(); leaf tokens don't.
            if hasattr(ident, "get_real_name"):
                parts = ident.get_real_name()
            else:
                parts = None
            if not parts:
                parts = ident.value
            return str(parts).strip().strip('"[]`')

        flat = list(parsed.flatten())
        for i, tok in enumerate(flat):
            if tok.ttype in (Keyword, Keyword.DML) and tok.value.upper() in (
                "FROM",
                "JOIN",
            ):
                for j in range(i + 1, min(i + 4, len(flat))):
                    nxt = flat[j]
                    if DatabaseManager._skippable(nxt):
                        continue
                    if nxt.value in ("(", ")"):
                        break  # subquery — its FROM appears later in the stream
                    if isinstance(nxt, (Identifier, IdentifierList)):
                        if isinstance(nxt, IdentifierList):
                            for sub in nxt.get_identifiers():
                                tables.add(table_of(sub))
                        else:
                            tables.add(table_of(nxt))
                    elif nxt.ttype in (Name, Keyword) and not nxt.is_keyword:
                        tables.add(table_of(nxt))
                    break
        return tables

    def validate_sql(self, sql: str, allowed_table: str) -> Tuple[bool, str]:
        """Return (ok, reason). `allowed_table` must be the ONLY table used."""
        if not sql or not sql.strip():
            return False, "Empty SQL statement"

        statements = sqlparse.split(sql)
        if len(statements) != 1:
            return False, "Multiple statements are not allowed"

        parsed = sqlparse.parse(statements[0])
        if not parsed:
            return False, "Unparseable SQL"
        statement = parsed[0]

        stmt_type = statement.get_type()
        if stmt_type not in ("SELECT", "UNKNOWN") and "WITH" not in sql[:20].upper():
            return False, f"Only SELECT statements are allowed (got {stmt_type!r})"

        upper = sql.upper()
        for word in FORBIDDEN_KEYWORDS:
            # Avoid false hits inside string literals: use word boundaries.
            if re.search(rf"\b{re.escape(word)}\b", upper):
                return False, f"Forbidden keyword: {word}"
        for frag in FORBIDDEN_FRAGMENTS:
            if frag.lower() in sql.lower():
                return False, f"Forbidden fragment: {frag}"
        if "--" in sql or "/*" in sql or "*/" in sql:
            return False, "SQL comments are not allowed"

        tables = self._extract_table_names(statement)
        # CTE names are aliases, not real tables — subtract them.
        cte_names = set(
            re.findall(r"\bWITH\s+([A-Za-z_][A-Za-z0-9_]*)\s+AS\b", sql)
        )
        cte_names |= set(
            re.findall(r"\)\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s+AS\b", sql)
        )
        tables -= cte_names
        if not tables:
            # Trivial SELECT without FROM is fine (e.g. SELECT 'CANNOT_ANSWER').
            return True, "Valid"
        if tables != {allowed_table}:
            return (
                False,
                f"Query references tables {sorted(tables)} but only "
                f"'{allowed_table}' is allowed",
            )
        return True, "Valid"

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def execute_query(
        self, sql: str, timeout_ms: Optional[int] = None
    ) -> pd.DataFrame:
        """Execute a validated SELECT. Raises SQLValidationError on unsafe SQL.

        The engine calls :meth:`validate_sql` with the real allowed table
        before reaching here; this method re-checks the structural rules so
        nothing dangerous can slip through on an un-validated path.
        """
        statements = sqlparse.split(sql)
        if len(statements) != 1:
            raise SQLValidationError("Multiple statements are not allowed")
        parsed = sqlparse.parse(statements[0])
        stmt_type = parsed[0].get_type() if parsed else None
        upper = sql.upper()
        if stmt_type not in ("SELECT", "UNKNOWN") and not upper.lstrip().startswith(
            "WITH"
        ):
            raise SQLValidationError(
                f"Only SELECT statements are allowed (got {stmt_type!r})"
            )
        if DANGEROUS_PATTERN.search(sql):
            raise SQLValidationError("Forbidden SQL construct detected")

        with self._lock:
            self._deadline = (
                time.monotonic() + (timeout_ms or self.timeout_ms) / 1000.0
            )
            try:
                df = pd.read_sql_query(sql, self._conn)
            except sqlite3.OperationalError as exc:
                if "timeout" in str(exc).lower():
                    raise sqlite3.OperationalError(
                        f"Query timed out after {(timeout_ms or self.timeout_ms)}ms"
                    ) from exc
                raise
            finally:
                self._deadline = None
        return df

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:  # pragma: no cover
                pass
