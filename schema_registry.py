"""Schema registry: CSV ingestion, inference, versioning, docs and search.

Implements the TRD §4 / §5.2 contract:
  * infer_schema   — encoding detection, units hints, categorical detection,
                     checksum, thematic tags
  * register_csv   — validate, sanitize table name, store a managed copy,
                     materialize the data table, record schema version 1
  * update_csv     — version bump + data table refresh + cache invalidation
  * get_schema_doc — LLM-facing schema documentation string
  * search_schemas — pure-Python TF-IDF cosine ranking over schema docs
  * delete_schema  — removes registry row and data table
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import chardet
import pandas as pd

from database import DatabaseManager

SUSTAINABILITY_KEYWORDS = [
    "carbon", "co2", "energy", "renewable", "water", "waste", "emission",
    "solar", "wind", "biomass", "recycling", "air quality", "climate",
    "green", "deforest", "biodiversity", "soil", "temperature", "rainfall",
    "methane", "nox", "so2", "pm2", "pm10", "electricity", "consumption",
    "generation", "capacity", "effluent", "discharge", "ph", "turbidity",
    "sustainability", "lagos", "kano", "nigeria", "ghg", "footprint",
]

UNITS_MAP = {
    "tons": "tons", "tonnes": "tonnes", "kwh": "kWh", "mwh": "MWh",
    "mw": "MW", "gw": "GW", "ph": "pH", "ntu": "NTU", "mpn": "MPN/100ml",
    "_c": "°C", "temp": "°C", "mm": "mm", "pct": "%", "percent": "%",
    "share": "%", "ppm": "ppm", "mg": "mg/L", "usd": "USD", "ngn": "NGN",
}

REGISTRY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_registry (
    table_id        TEXT PRIMARY KEY,
    table_name      TEXT NOT NULL UNIQUE,
    file_name       TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    row_count       INTEGER NOT NULL,
    column_count    INTEGER NOT NULL,
    schema_doc      TEXT NOT NULL,
    columns_json    TEXT NOT NULL,
    thematic_tags   TEXT,
    version         INTEGER DEFAULT 1,
    checksum        TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

REGISTRY_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_schema_thematic ON schema_registry(thematic_tags)",
    "CREATE INDEX IF NOT EXISTS idx_schema_filename ON schema_registry(file_name)",
    "CREATE INDEX IF NOT EXISTS idx_schema_version ON schema_registry(table_name, version)",
)


class CSVValidationError(ValueError):
    """Raised when an uploaded CSV fails validation (E009)."""


class SchemaRegistry:
    def __init__(self, db: DatabaseManager, data_dir: str = "data") -> None:
        self._db = db
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_registry_table()

    # ------------------------------------------------------------------
    # Registry table bootstrap
    # ------------------------------------------------------------------
    def _ensure_registry_table(self) -> None:
        self._db.execute_raw(REGISTRY_TABLE_SQL)
        for idx in REGISTRY_INDEXES:
            self._db.execute_raw(idx)

    # ------------------------------------------------------------------
    # CSV validation (E009)
    # ------------------------------------------------------------------
    def validate_csv(self, file_path: str) -> Tuple[bool, str]:
        p = Path(file_path)
        if not p.exists():
            return False, "File does not exist"
        if p.suffix.lower() != ".csv":
            return False, f"Only .csv files are supported (got {p.suffix or 'none'})"
        if p.stat().st_size == 0:
            return False, "File is empty"
        if p.stat().st_size > 20 * 1024 * 1024:
            return False, "File exceeds the 20MB upload limit"
        try:
            df, enc = self._read_csv(p)
        except Exception as exc:  # noqa: BLE001
            return False, f"Could not parse CSV: {exc}"

        # Header-level checks from the RAW first line (pandas mangles
        # duplicate names and coerces numeric headers, so inspect text).
        import csv as _csv

        try:
            with open(p, encoding=enc, errors="replace") as fh:
                first = fh.readline()
            fields = next(_csv.reader([first]))
        except Exception as exc:  # noqa: BLE001
            return False, f"Unreadable header row: {exc}"
        if not first.strip() or not fields:
            return False, "CSV contains no header row"
        if len(fields) != len(set(fields)):
            dupes = sorted({f for f in fields if fields.count(f) > 1})
            return False, f"Duplicate column names: {dupes}"
        if any(str(f).strip() == "" for f in fields):
            return False, "Column names must not be empty"

        if df.empty:
            return False, "CSV contains no data rows"
        if all(self._looks_numeric(c) for c in df.columns.tolist()):
            return False, "CSV appears to have no header row"
        return True, ""

    @staticmethod
    def _looks_numeric(value: Any) -> bool:
        if isinstance(value, (int, float)):
            return True
        try:
            float(str(value))
            return True
        except (TypeError, ValueError):
            return False

    def _read_csv(self, path: Path) -> Tuple[pd.DataFrame, str]:
        raw = path.read_bytes()[:100_000]
        detected = chardet.detect(raw)
        encoding = detected.get("encoding") or "utf-8"
        for enc in (encoding, "utf-8", "latin-1"):
            try:
                df = pd.read_csv(path, encoding=enc)
                return df, enc
            except (UnicodeDecodeError, pd.errors.ParserError):
                continue
        raise ValueError("unrecognized file encoding")

    # ------------------------------------------------------------------
    # Schema inference
    # ------------------------------------------------------------------
    def infer_schema(self, csv_path: str, table_id: Optional[str] = None) -> Dict[str, Any]:
        p = Path(csv_path)
        df, _enc = self._read_csv(p)

        columns: List[Dict[str, Any]] = []
        for name in df.columns:
            col = df[name]
            sample = [None if pd.isna(v) else v for v in col.head(3).tolist()]
            numeric = pd.to_numeric(col, errors="coerce")
            entry: Dict[str, Any] = {
                "name": str(name),
                "dtype": str(col.dtype),
                "sample_values": sample,
                "min": None,
                "max": None,
                "unique_count": int(col.nunique(dropna=True)),
                "null_count": int(col.isna().sum()),
                "description": self._describe_column(str(name)),
                "units_hint": self._extract_units(str(name)),
                "categorical_values": None,
            }
            if numeric.notna().any():
                entry["min"] = float(numeric.min())
                entry["max"] = float(numeric.max())
            if col.dtype == object and col.nunique(dropna=True) <= 20:
                tops = col.dropna().astype(str).value_counts().head(5).index.tolist()
                entry["categorical_values"] = tops
            columns.append(entry)

        tags = self._thematic_tags(p.name, columns, df)
        return {
            "table_id": table_id,
            "file_name": p.name,
            "row_count": int(len(df)),
            "column_count": int(len(df.columns)),
            "columns": columns,
            "thematic_tags": tags,
            "checksum": self._checksum(p),
        }

    @staticmethod
    def _describe_column(name: str) -> str:
        base = name.replace("_", " ").strip().lower()
        return f"Column '{name}' ({base})"

    @staticmethod
    def _extract_units(name: str) -> Optional[str]:
        low = name.lower()
        for key, unit in UNITS_MAP.items():
            if key in low:
                return unit
        return None

    @staticmethod
    def _checksum(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def _thematic_tags(
        self, filename: str, columns: List[Dict[str, Any]], df: pd.DataFrame
    ) -> List[str]:
        haystack = filename.lower() + " " + " ".join(c["name"] for c in columns)
        for col in columns:
            if col["categorical_values"]:
                haystack += " " + " ".join(str(v) for v in col["categorical_values"])
        tags = [k for k in SUSTAINABILITY_KEYWORDS if k in haystack]
        return tags[:12]

    # ------------------------------------------------------------------
    # Table naming (TRD §4.3)
    # ------------------------------------------------------------------
    def _sanitize_table_name(self, filename: str, table_id: str) -> str:
        stem = Path(filename).stem.lower()
        stem = unicodedata.normalize("NFKD", stem)
        stem = re.sub(r"[^a-z0-9]+", "_", stem)
        stem = re.sub(r"_+", "_", stem).strip("_")
        stem = stem[:63] or "table"
        candidate = f"csv_{table_id}_{stem}"
        existing = set(self._db.list_tables())
        if candidate in existing:
            suffix = hashlib.sha256(stem.encode()).hexdigest()[:6]
            candidate = f"csv_{table_id}_{stem[:52]}_{suffix}"
        return candidate

    # ------------------------------------------------------------------
    # Register / update / delete
    # ------------------------------------------------------------------
    def register_csv(
        self,
        csv_path: str,
        thematic_tags: Optional[List[str]] = None,
        table_id: Optional[str] = None,
    ) -> str:
        ok, reason = self.validate_csv(csv_path)
        if not ok:
            raise CSVValidationError(reason)

        table_id = table_id or self._next_table_id()
        info = self.infer_schema(csv_path, table_id=table_id)
        table_name = self._sanitize_table_name(info["file_name"], table_id)

        managed = self._data_dir / f"{table_id}_{info['file_name']}"
        shutil.copy2(csv_path, managed)

        df, _ = self._read_csv(Path(csv_path))
        self._db.create_table_from_df(df, table_name, if_exists="replace")

        tags = json.dumps(thematic_tags or info["thematic_tags"])
        columns_json = json.dumps(info["columns"], default=str)
        doc = self._build_doc(table_id, table_name, info)

        self._db.execute_raw(
            """
            INSERT INTO schema_registry
                (table_id, table_name, file_name, file_path, row_count,
                 column_count, schema_doc, columns_json, thematic_tags,
                 version, checksum)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(table_id) DO UPDATE SET
                table_name=excluded.table_name,
                file_name=excluded.file_name,
                file_path=excluded.file_path,
                row_count=excluded.row_count,
                column_count=excluded.column_count,
                schema_doc=excluded.schema_doc,
                columns_json=excluded.columns_json,
                thematic_tags=excluded.thematic_tags,
                version=excluded.version,
                checksum=excluded.checksum,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                table_id, table_name, info["file_name"], str(managed),
                info["row_count"], info["column_count"], doc, columns_json,
                tags, info["checksum"],
            ),
        )
        return table_id

    def _next_table_id(self) -> str:
        with sqlite3.connect(self._db.db_path) as conn:
            row = conn.execute("SELECT COUNT(*) c FROM schema_registry").fetchone()
        return f"{int(row[0]) + 1:03d}"

    def update_csv(self, table_id: str, new_csv_path: str) -> str:
        meta = self.get_meta(table_id)
        if not meta:
            raise KeyError(f"Unknown table_id: {table_id}")
        ok, reason = self.validate_csv(new_csv_path)
        if not ok:
            raise CSVValidationError(reason)

        info = self.infer_schema(new_csv_path, table_id=table_id)
        version = meta["version"] + 1
        table_name = meta["table_name"]

        managed = self._data_dir / f"{table_id}_{info['file_name']}"
        shutil.copy2(new_csv_path, managed)
        df, _ = self._read_csv(Path(new_csv_path))
        self._db.create_table_from_df(df, table_name, if_exists="replace")

        columns_json = json.dumps(info["columns"], default=str)
        doc = self._build_doc(table_id, table_name, info)
        self._db.execute_raw(
            """
            UPDATE schema_registry SET
                file_name=?, file_path=?, row_count=?, column_count=?,
                schema_doc=?, columns_json=?, version=?, checksum=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE table_id=?
            """,
            (
                info["file_name"], str(managed), info["row_count"],
                info["column_count"], doc, columns_json, version,
                info["checksum"], table_id,
            ),
        )
        return table_id

    def delete_schema(self, table_id: str) -> bool:
        meta = self.get_meta(table_id)
        if not meta:
            return False
        self._db.execute_raw(
            f'DROP TABLE IF EXISTS "{meta["table_name"]}"'
        )
        self._db.execute_raw(
            "DELETE FROM schema_registry WHERE table_id=?", (table_id,)
        )
        try:
            Path(meta["file_path"]).unlink(missing_ok=True)
        except OSError:
            pass
        return True

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def list_tables(self) -> List[str]:
        """Data tables currently registered (passthrough to the DB layer)."""
        return self._db.list_tables()

    def get_meta(self, table_id: str) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self._db.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM schema_registry WHERE table_id=?", (table_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_metas(
        self, table_ids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Batch meta fetch — ONE connection instead of one per table.

        With hundreds of registered tables, calling :meth:`get_meta` in a
        loop opens a new SQLite connection per call on every UI rerun.
        Pass ``table_ids=None`` (or omit) for ALL rows; an empty list
        returns no rows.
        """
        q = "SELECT * FROM schema_registry"
        params: Tuple[Any, ...] = ()
        if table_ids is not None:
            # Chunk the IN clause so a 1000+ table registry never trips
            # SQLite's max-variable limit (usually 999 in CPython builds).
            ids = list(table_ids)
            chunks = [ids[i : i + 400] for i in range(0, len(ids), 400)]
            out: List[Dict[str, Any]] = []
            for chunk in chunks:
                placeholders = ",".join("?" * len(chunk))
                with sqlite3.connect(self._db.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    rows = conn.execute(
                        q + f" WHERE table_id IN ({placeholders}) ORDER BY table_id",
                        tuple(chunk),
                    ).fetchall()
                out.extend(dict(r) for r in rows)
            return out
        with sqlite3.connect(self._db.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(q + " ORDER BY table_id").fetchall()
        return [dict(r) for r in rows]

    def get_all_schemas(self) -> List[Tuple[str, str, str, List[str]]]:
        """Return (table_id, table_name, schema_doc, tags) for every table."""
        with sqlite3.connect(self._db.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT table_id, table_name, schema_doc, thematic_tags "
                "FROM schema_registry ORDER BY table_id"
            ).fetchall()
        out = []
        for r in rows:
            tags = []
            if r["thematic_tags"]:
                try:
                    tags = json.loads(r["thematic_tags"])
                except json.JSONDecodeError:
                    tags = [r["thematic_tags"]]
            out.append((r["table_id"], r["table_name"], r["schema_doc"], tags))
        return out

    def get_schema_doc(self, table_id: str, version: Optional[int] = None) -> str:
        meta = self.get_meta(table_id)
        if not meta:
            raise KeyError(f"Unknown table_id: {table_id}")
        if version is not None and version != meta["version"]:
            raise KeyError(
                f"table {table_id} is at version {meta['version']}, "
                f"requested {version}"
            )
        return meta["schema_doc"]

    def get_table_name(self, table_id: str) -> str:
        meta = self.get_meta(table_id)
        if not meta:
            raise KeyError(f"Unknown table_id: {table_id}")
        return meta["table_name"]

    # ------------------------------------------------------------------
    # Schema documentation (LLM-facing)
    # ------------------------------------------------------------------
    def _build_doc(self, table_id: str, table_name: str, info: Dict[str, Any]) -> str:
        lines = [f"TABLE: {table_name}", f"TABLE_ID: {table_id}"]
        lines.append(f"ROWS: {info['row_count']}  COLUMNS: {info['column_count']}")
        lines.append("COLUMNS:")
        for c in info["columns"]:
            parts = [f"- {c['name']} ({c['dtype']})"]
            notes = []
            if c["units_hint"]:
                notes.append(f"unit: {c['units_hint']}")
            if c["null_count"]:
                pct = c["null_count"] / max(info["row_count"], 1) * 100
                notes.append(f"{pct:.0f}% nulls — use COALESCE/IS NULL")
            if c["min"] is not None and c["max"] is not None:
                notes.append(f"range {c['min']:g}..{c['max']:g}")
            if c["categorical_values"]:
                notes.append(f"values: {', '.join(map(str, c['categorical_values']))}")
            lines.append("  " + parts[0] + (" (" + "; ".join(notes) + ")" if notes else ""))
        lines.append("NOTES:")
        for c in info["columns"]:
            low = c["name"].lower()
            if "year" in low or "date" in low:
                lines.append(
                    f"- '{c['name']}' is a date/year column; filter with =, <, > "
                    "and GROUP BY it directly."
                )
        lines.append("- Aggregations (SUM/AVG/COUNT) should include all "
                     "non-aggregated columns in GROUP BY.")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # TF-IDF search (pure Python, TRD §6.5)
    # ------------------------------------------------------------------
    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return re.findall(r"[a-z0-9_]+", text.lower())

    def search_schemas(self, query: str, top_k: int = 5) -> List[Tuple[str, float]]:
        schemas = self.get_all_schemas()
        if not schemas:
            return []
        docs = []
        for _tid, _tname, doc, tags in schemas:
            docs.append(doc + " " + " ".join(tags))

        # Document frequency for idf.
        doc_tokens = [set(self._tokenize(d)) for d in docs]
        df_counts: Dict[str, int] = {}
        for toks in doc_tokens:
            for t in toks:
                df_counts[t] = df_counts.get(t, 0) + 1
        n = len(docs)
        idf = {t: 1.0 + (n / (1 + c)) ** 0.5 for t, c in df_counts.items()}

        def vectorize(text: str) -> Dict[str, float]:
            counts: Dict[str, float] = {}
            for t in self._tokenize(text):
                counts[t] = counts.get(t, 0.0) + 1.0
            norm = sum(v * v for v in counts.values()) ** 0.5 or 1.0
            return {t: (v / norm) * idf.get(t, 1.0) for t, v in counts.items()}

        qv = vectorize(query)
        scored = []
        for i, d in enumerate(docs):
            dv = vectorize(d)
            dot = sum(qv.get(t, 0.0) * dv.get(t, 0.0) for t in qv)
            scored.append((schemas[i][0], round(dot, 4)))
        scored.sort(key=lambda x: x[1], reverse=True)

        # Keyword-overlap fallback for ties / cold start.
        if scored[0][1] <= 0.0:
            q_tokens = set(self._tokenize(query))
            overlap = []
            for i, d in enumerate(docs):
                score = len(q_tokens & doc_tokens[i])
                overlap.append((schemas[i][0], float(score)))
            overlap.sort(key=lambda x: x[1], reverse=True)
            scored = overlap
        return [s for s in scored if s[1] > 0.0][:top_k]

    # ------------------------------------------------------------------
    def stats(self) -> Dict[str, Any]:
        metas = [self.get_meta(tid) for tid, *_ in self.get_all_schemas()]
        return {
            "tables": len(metas),
            "total_rows": sum(m["row_count"] for m in metas if m),
            "versions": [m["version"] for m in metas if m],
        }
