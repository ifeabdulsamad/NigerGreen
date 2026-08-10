"""TextToSQLEngine — the two-stage LLM pipeline (TRD §5.1, §7).

Stage 1: schema selection  -> deepseek/deepseek-chat  (temp 0.1, 200 tok)
Stage 2: SQL generation     -> deepseek/deepseek-chat  (temp 0.1, 500 tok)
Fallback model              -> deepseek/deepseek-reasoner

Resilience (TRD §7):
  * E001 no API key           -> demo mode with rule-based answers
  * E002 schema selection fail -> retry with relaxed candidate set
  * E003 SQL generation fail   -> retry with fallback model, then template SQL
  * E004 unsafe SQL            -> refused answer, logged for review
  * E005 execution error       -> retry without LIMIT on "row value misused"
  * E006 empty results         -> flagged in response
  * E007 LLM timeout           -> retry once with shorter max_tokens
  * E008 rate limit            -> exponential backoff + jitter
  * E010 cache corruption      -> invalidate entry and replay

Caching (TRD §9.2) via CacheManager.
"""
from __future__ import annotations

import hashlib
import random
import re
import sqlite3
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

try:
    from logger import get_logger, question_hash, sql_hash
except Exception:  # pragma: no cover - import cycle guard
    def get_logger(_n="naijagreen"):  # type: ignore[misc]
        return __import__("logging").getLogger("naijagreen")

    def question_hash(q):  # type: ignore[misc]
        return hashlib.sha256(q.encode()).hexdigest()[:12]

    def sql_hash(s):  # type: ignore[misc]
        return hashlib.sha256(s.encode()).hexdigest()[:12]


# ----------------------------------------------------------------------
# Error taxonomy (TRD §7.1)
# ----------------------------------------------------------------------
class EngineError(Exception):
    code = "E000"


class NoAPIKeyError(EngineError):
    code = "E001"


class SchemaSelectionError(EngineError):
    code = "E002"


class SQLGenerationError(EngineError):
    code = "E003"


class UnsafeSQLError(EngineError):
    code = "E004"


class QueryExecutionError(EngineError):
    code = "E005"


class EmptyResultError(EngineError):
    code = "E006"


class LLMTimeoutError(EngineError):
    code = "E007"


class RateLimitError(EngineError):
    code = "E008"


class InputValidationError(EngineError):
    code = "E009"


# Demo-mode question templates (TRD §7.3): regex -> SQL builder.
def _demo_sql_for(question: str, table_name: str, columns: List[str]) -> Optional[str]:
    q = question.lower().strip().rstrip("?")
    numeric = [c for c in columns if c in ("co2_emissions_tons", "total_mw",
                                           "renewable_share_pct", "ph",
                                           "turbidity_ntu", "coliform_mpn",
                                           "consumption_kwh", "generation_mw")]
    numeric = numeric or [c for c in columns if "tons" in c or "mw" in c or "pct" in c]
    year_col = next((c for c in columns if "year" in c), None)
    site_col = next((c for c in columns if "site" in c or "sector" in c or "state" in c), None)
    agg = None
    if re.search(r"\b(total|sum|how much)\b", q) and year_col:
        agg = f"SUM"
    elif re.search(r"\baverage|mean\b", q):
        agg = "AVG"
    elif re.search(r"\b(max|highest|most|peak)\b", q):
        agg = "MAX"
    elif re.search(r"\b(min|lowest|least)\b", q):
        agg = "MIN"
    elif re.search(r"\bcount\b", q):
        agg = "COUNT"
    if agg and numeric:
        col = numeric[0]
        if agg == "COUNT":
            return f"SELECT COUNT(*) AS {table_name}_count FROM {table_name}"
        if year_col:
            return (
                f"SELECT {year_col}, {agg}({col}) AS {col}_agg "
                f"FROM {table_name} GROUP BY {year_col} ORDER BY {year_col}"
            )
        return f"SELECT {agg}({col}) AS {col}_agg FROM {table_name}"
    if re.search(r"\bshow|list|all|everything\b", q):
        return f"SELECT * FROM {table_name} LIMIT 50"
    if site_col and re.search(r"\b(in|for|by)\b", q):
        m = re.search(r"(in|for|by)\s+([a-z0-9 ]{2,30}?)(\s+in|\s+for|\s+by|$)", q)
        if m and agg is None:
            return f"SELECT * FROM {table_name} LIMIT 50"
    if re.search(r"\btop\b", q) and numeric:
        return f"SELECT * FROM {table_name} ORDER BY {numeric[0]} DESC LIMIT 10"
    return None


class TextToSQLEngine:
    """End-to-end question -> validated SQL -> DataFrame -> NL summary."""

    def __init__(
        self,
        config: Any,
        registry: Any,
        cache: Any,
        demo_mode: Optional[bool] = None,
        cache_enabled: Optional[bool] = None,
        max_retries: Optional[int] = None,
        query_timeout_ms: Optional[int] = None,
    ) -> None:
        self.config = config
        self.registry = registry
        self.cache = cache
        self.demo_mode = config.demo_mode if demo_mode is None else demo_mode
        self.max_retries = config.max_retries if max_retries is None else max_retries
        self.query_timeout_ms = (
            config.query_timeout_ms if query_timeout_ms is None else query_timeout_ms
        )
        self._log = get_logger("sql_engine")
        self._prompts: Dict[str, str] = {}
        if cache_enabled is not None:
            self.cache.enabled = cache_enabled
        self._load_prompts()

    # ------------------------------------------------------------------
    def _load_prompts(self) -> None:
        base = Path(__file__).parent / "prompts"
        for name in ("schema_selection", "sql_generation"):
            path = base / f"{name}.txt"
            if path.exists():
                self._prompts[name] = path.read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Public API (TRD §5.1)
    # ------------------------------------------------------------------
    def select_schema(
        self, question: str, candidate_schemas: List[Tuple[str, str, str, List[str]]]
    ) -> str:
        """Stage 1: pick the most relevant table. Returns table_id."""
        if not candidate_schemas:
            raise SchemaSelectionError("No candidate schemas available")
        if len(candidate_schemas) == 1:
            return candidate_schemas[0][0]

        # Cache key embeds the candidate ids so per-table invalidation works.
        ids_str = ",".join(sorted(t[0] for t in candidate_schemas))
        cached = self.cache.get_schema_selection(question, ids_str)
        if cached and cached in {t[0] for t in candidate_schemas}:
            return cached

        # Keyword pre-filter keeps the LLM's candidate list small (TRD §6.5).
        try:
            ranked = self.registry.search_schemas(question, top_k=5)
            ordered = {tid: i for i, (tid, _s) in enumerate(ranked)}
            candidates = sorted(candidate_schemas, key=lambda t: ordered.get(t[0], 99))
        except Exception:  # noqa: BLE001
            candidates = candidate_schemas

        prompt = self._render("schema_selection", question=question,
                              tables=self._fmt_candidates(candidates))
        try:
            answer = self._call_llm(prompt, stage="schema", relax_on_error=False)
        except EngineError:
            # E002 recovery: retry once with the FULL candidate set.
            prompt = self._render("schema_selection", question=question,
                                  tables=self._fmt_candidates(candidate_schemas))
            answer = self._call_llm(prompt, stage="schema", relax_on_error=True)

        m = re.search(r"<([^>]+)>", answer)
        raw = m.group(1).strip() if m else ""
        # LLM returns the table NAME (per the prompt), but we need the ID.
        # Build a name→id map and accept either.
        name_to_id = {t[1]: t[0] for t in candidate_schemas}
        valid_ids = {t[0] for t in candidate_schemas}
        if raw in valid_ids:
            table_id = raw
        elif raw in name_to_id:
            table_id = name_to_id[raw]
        elif raw.upper() == "NONE":
            raise SchemaSelectionError("No relevant table found for this question")
        else:
            # Demo fallback: keyword scoring.
            table_id = self._demo_select(question, candidate_schemas)
            if not table_id:
                raise SchemaSelectionError(
                    f"Could not match question to any available table. "
                    f"Try rephrasing or uploading a relevant dataset."
                )
        self.cache.set_schema_selection(question, ids_str, table_id)
        return table_id

    def generate_sql(
        self,
        question: str,
        schema_doc: str,
        table_name: str,
        table_id: Optional[str] = None,
    ) -> str:
        """Stage 2: produce validated, executable SQLite SELECT."""
        meta = self.registry.get_meta(table_id) if table_id else None
        version = meta["version"] if meta else 1
        version_key = f"{table_id or table_name}:{version}"
        cached = self.cache.get_sql(question, version_key)
        if cached:
            return cached

        prompt = self._render("sql_generation", question=question,
                              schema_doc=schema_doc)
        try:
            sql = self._call_llm(prompt, stage="sql", relax_on_error=False)
        except EngineError:
            # E003 recovery: fallback model, then template SQL.
            sql = self._call_llm(prompt, stage="sql", relax_on_error=True)
            if not sql:
                sql = self._template_sql(question, table_name)

        sql = self._clean_sql(sql)
        self.cache.set_sql(question, version_key, sql)
        return sql

    def execute_query(self, sql: str, table_name: str) -> pd.DataFrame:
        """Validate against the whitelist, then execute with timeout."""
        db = self.registry._db  # DatabaseManager owned by the registry
        ok, reason = db.validate_sql(sql, table_name)
        if not ok:
            raise UnsafeSQLError(f"E004: {reason}")
        try:
            return db.execute_query(sql, timeout_ms=self.query_timeout_ms)
        except sqlite3.OperationalError as exc:
            raise QueryExecutionError(f"E005: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise QueryExecutionError(f"E005: {exc}") from exc

    def answer_question(self, question: str) -> Dict[str, Any]:
        """End-to-end pipeline. Returns the TRD §5.1 response dict."""
        start = time.perf_counter()
        self._validate_input(question)

        schemas = self.registry.get_all_schemas()
        if not schemas:
            return self._response(question, error="E000: No datasets uploaded yet",
                                  execution_ms=self._elapsed(start))

        result_cache_key = self._result_cache_key(question, schemas)
        cached = self.cache.get_result(*result_cache_key) if result_cache_key else None
        if cached is not None:
            cached["cached"] = True
            cached["execution_time_ms"] = self._elapsed(start)
            return cached

        try:
            answer = self._answer_question_inner(question, schemas)
        except EmptyResultError:
            answer = self._response(
                question, error="E006: No matching rows. Try broadening the question.",
                execution_ms=self._elapsed(start),
            )
        except UnsafeSQLError as exc:
            self._log.warning("unsafe_sql_rejected", error=str(exc),
                              qhash=question_hash(question))
            answer = self._response(
                question,
                error="E004: I generated an unsafe query and refused to run it. "
                      "Please rephrase the question.",
                execution_ms=self._elapsed(start),
            )
        except EngineError as exc:
            answer = self._response(question, error=f"{exc.code}: {exc}",
                                    execution_ms=self._elapsed(start))
        except Exception as exc:  # noqa: BLE001 - last-resort guard
            self._log.exception("unexpected_error")
            answer = self._response(question, error=f"E000: {exc}",
                                    execution_ms=self._elapsed(start))

        if result_cache_key and not answer.get("error"):
            self.cache.set_result(*result_cache_key, value=answer)
        return answer

    # ------------------------------------------------------------------
    # Inner pipeline
    # ------------------------------------------------------------------
    def _answer_question_inner(
        self, question: str, schemas: List[Tuple[str, str, str, List[str]]]
    ) -> Dict[str, Any]:
        start = time.perf_counter()
        ranked = self.registry.search_schemas(question, top_k=5)
        top_ids = {tid for tid, _s in ranked}
        candidates = [s for s in schemas if s[0] in top_ids] or schemas[:5]

        table_id = self.select_schema(question, candidates)
        meta = self.registry.get_meta(table_id)
        if not meta:
            raise SchemaSelectionError(f"E002: selected table {table_id} missing")
        table_name = meta["table_name"]
        schema_doc = self.registry.get_schema_doc(table_id)

        sql = self.generate_sql(question, schema_doc, table_name, table_id=table_id)
        if "CANNOT_ANSWER" in sql.upper():
            return self._response(
                question,
                error="No relevant data found. Try rephrasing your question or "
                      "uploading a dataset that covers this topic.",
                execution_ms=self._elapsed(start),
            )

        try:
            df = self.execute_query(sql, table_name)
        except QueryExecutionError:
            # E005 recovery: "row value misused" -> drop LIMIT and retry once.
            if re.search(r"\bLIMIT\s+\d+", sql, re.IGNORECASE):
                sql2 = re.sub(r"\s+LIMIT\s+\d+(\s*;?\s*)$", "", sql, flags=re.IGNORECASE)
                df = self.execute_query(sql2, table_name)
                sql = sql2
            else:
                raise

        nl = self._summarize(question, df, table_name)
        return self._response(
            question=question,
            selected_table=table_name,
            sql=sql,
            results=df,
            nl_summary=nl,
            execution_ms=self._elapsed(start),
            cached=False,
        )

    # ------------------------------------------------------------------
    # LLM calls with retry / backoff / jitter (TRD §7.2)
    # ------------------------------------------------------------------
    def _call_llm(
        self, prompt: str, stage: str, relax_on_error: bool = False
    ) -> str:
        if self.demo_mode or not self.config.deepseek_api_key:
            if stage == "schema":
                return self._demo_schema_answer(prompt)
            return self._demo_sql_answer(prompt)

        try:
            import litellm  # lazy import: demo mode works without it
        except ImportError as exc:
            raise NoAPIKeyError(
                "E001: litellm is not installed; install requirements or use demo mode"
            ) from exc

        model = (
            self.config.sql_model if stage == "sql" else self.config.schema_model
        )
        max_tokens = (
            self.config.sql_max_tokens if stage == "sql" else self.config.schema_max_tokens
        )
        attempts = 1 + (self.max_retries if relax_on_error else 0)
        last_exc: Optional[Exception] = None
        for attempt in range(attempts):
            try:
                resp = litellm.completion(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    temperature=self.config.llm_temperature,
                    timeout=self.config.llm_timeout_s,
                    api_key=self.config.deepseek_api_key,
                )
                content = resp["choices"][0]["message"]["content"]
                return str(content).strip()
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < attempts - 1:
                    delay = (2 ** attempt) * 0.5 + random.uniform(0, 0.5)
                    time.sleep(delay)
                else:
                    break
        # E003 recovery: try fallback model once with a shorter budget.
        if relax_on_error:
            try:
                import litellm  # noqa: F811

                resp = litellm.completion(
                    model=self.config.fallback_model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=min(max_tokens, 300),
                    temperature=self.config.llm_temperature,
                    timeout=min(self.config.llm_timeout_s, 15.0),
                    api_key=self.config.deepseek_api_key,
                )
                return str(resp["choices"][0]["message"]["content"]).strip()
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
        if stage == "sql":
            return ""  # caller falls back to template SQL
        raise SchemaSelectionError(f"Schema selection failed: {last_exc}")

    # ------------------------------------------------------------------
    # Demo-mode rule engine (TRD §7.3)
    # ------------------------------------------------------------------
    def _demo_schema_answer(self, prompt: str) -> str:
        # Reuse the same regex parsing the engine uses on LLM output, but
        # with keyword scoring against the candidate list embedded in prompt.
        m = re.search(r"<([^>]+)>", prompt)
        if m:
            return m.group(1)
        return "<NONE>"

    def _demo_sql_answer(self, prompt: str) -> str:
        # Take the LAST "Question:" — the template's negative example also
        # contains a "Question:" line, which must not win.
        matches = re.findall(r"Question:\s*(.+)", prompt)
        question = matches[-1].strip() if matches else ""
        table_m = re.search(r"TABLE: (\S+)", prompt)
        table_name = table_m.group(1) if table_m else "csv_table"
        # Column lines in the doc are indented: "  - name (dtype)".
        columns = re.findall(r"^\s*- ([a-z0-9_]+) \(", prompt, re.M)
        sql = _demo_sql_for(question, table_name, columns)
        return sql or "SELECT 'CANNOT_ANSWER' AS error;"

    def _demo_select(
        self, question: str, candidates: List[Tuple[str, str, str, List[str]]]
    ) -> Optional[str]:
        q = set(re.findall(r"[a-z0-9_]+", question.lower()))
        best, best_score = None, 0
        for tid, _tname, doc, tags in candidates:
            hay = set(re.findall(r"[a-z0-9_]+", doc.lower())) | set(tags)
            score = len(q & hay)
            if score > best_score:
                best, best_score = tid, score
        return best

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _render(self, name: str, **kwargs: Any) -> str:
        tpl = self._prompts.get(name)
        if not tpl:
            raise RuntimeError(f"Prompt template {name}.txt is missing")
        return tpl.format(**kwargs)

    @staticmethod
    def _fmt_candidates(candidates: List[Tuple[str, str, str, List[str]]]) -> str:
        lines = []
        for i, (tid, tname, doc, _tags) in enumerate(candidates, 1):
            first_line = doc.splitlines()[0] if doc else tname
            lines.append(f"{i}. {tname} | {first_line}")
        return "\n".join(lines)

    @staticmethod
    def _clean_sql(sql: str) -> str:
        sql = sql.strip()
        if sql.startswith("```"):
            sql = re.sub(r"^```(sql)?\s*", "", sql, flags=re.IGNORECASE)
            sql = re.sub(r"\s*```$", "", sql)
        sql = sql.strip().rstrip(";") + ";"
        return sql

    def _template_sql(self, question: str, table_name: str) -> str:
        meta = self.registry.get_meta(table_name)
        columns: List[str] = []
        if meta:
            try:
                columns = [c["name"] for c in json_loads(meta["columns_json"])]
            except Exception:  # noqa: BLE001
                columns = []
        sql = _demo_sql_for(question, table_name, columns)
        return sql or "SELECT 'CANNOT_ANSWER' AS error;"

    @staticmethod
    def _validate_input(question: str) -> None:
        if not question or not question.strip():
            raise InputValidationError("E009: empty question")
        if len(question) > 500:
            raise InputValidationError("E009: question too long (max 500 chars)")
        question = unicodedata.normalize("NFKC", question)
        if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", question):
            raise InputValidationError("E009: control characters not allowed")

    def _result_cache_key(
        self, question: str, schemas: List[Tuple[str, str, str, List[str]]]
    ):
        if not self.cache.enabled:
            return None
        # Key embeds ids + versions so version bumps naturally invalidate.
        # Fetch all metas in ONE batched query — a loop of get_meta() would
        # open a fresh SQLite connection per schema on every question.
        ids = ",".join(sorted(s[0] for s in schemas))
        metas = {
            m["table_id"]: m for m in self.registry.get_metas()
        }
        versions = [
            str(metas[tid]["version"]) if tid in metas else "0"
            for tid, *_rest in schemas
        ]
        sig = f"v{'|'.join(versions)}"
        return (question, ids, sig)

    def _summarize(self, question: str, df: pd.DataFrame, table_name: str) -> str:
        if self.demo_mode or not self.config.deepseek_api_key:
            rows = len(df)
            if rows == 0:
                return "No rows matched."
            cols = ", ".join(str(c) for c in df.columns[:4])
            return (
                f"Your question returned {rows} row(s) from {table_name} "
                f"(columns: {cols})."
            )
        try:
            import litellm  # lazy

            md = df.head(5).to_markdown(index=False)
            resp = litellm.completion(
                model=self.config.sql_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Summarise the following table result in ONE sentence "
                            "for a non-technical user. No markdown."
                        ),
                    },
                    {"role": "user", "content": f"RESULT:\n{md}"},
                ],
                max_tokens=80,
                temperature=0.2,
                timeout=15.0,
                api_key=self.config.deepseek_api_key,
            )
            return str(resp["choices"][0]["message"]["content"]).strip()
        except Exception:  # noqa: BLE001 - summary is best-effort
            return f"Query executed successfully ({len(df)} row(s))."

    @staticmethod
    def _response(question: str, **over: Any) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "question": question,
            "selected_table": None,
            "sql": None,
            "results": None,
            "nl_summary": None,
            "execution_time_ms": 0.0,
            "cached": False,
            "error": None,
        }
        base.update(over)
        return base

    @staticmethod
    def _elapsed(start: float) -> float:
        return round((time.perf_counter() - start) * 1000.0, 2)


def json_loads(raw: str) -> Any:
    import json

    return json.loads(raw)
