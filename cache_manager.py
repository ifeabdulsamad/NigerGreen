"""TTL-based caching for schema selections, SQL generations and query results.

Design (TRD §9.2):
  - schema selection : key (question, candidate_table_ids_hash), TTL 30 min
  - sql generation    : key (question, schema_version),           TTL 1 hour
  - query results     : key (sql, table_name, result_hash),       TTL 5 min
  - schema documents  : key table_id:version,                     session-scoped

All caches are in-memory (cachetools), respect demo mode, and are
invalidated wholesale for a table when its schema version bumps.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

from cachetools import LRUCache, TTLCache


class CacheManager:
    """Thread-safe TTL cache facade used by the SQL engine."""

    def __init__(
        self,
        enabled: bool = True,
        schema_ttl_s: int = 1800,
        sql_ttl_s: int = 3600,
        result_ttl_s: int = 300,
        max_entries: int = 200,
    ) -> None:
        self.enabled = enabled
        self._lock = threading.RLock()
        self._schema: TTLCache = TTLCache(maxsize=max_entries, ttl=schema_ttl_s)
        self._sql: TTLCache = TTLCache(maxsize=max_entries, ttl=sql_ttl_s)
        self._docs: LRUCache = LRUCache(maxsize=max_entries)
        # Results store value + inserted-at so we can enforce TTL on access.
        self._results: LRUCache = LRUCache(maxsize=max_entries)
        self._result_ttl = result_ttl_s
        self._hits = {"schema": 0, "sql": 0, "result": 0, "doc": 0}
        self._misses = {"schema": 0, "sql": 0, "result": 0, "doc": 0}

    # ------------------------------------------------------------------
    def _get(self, store: str, key: str) -> Optional[Any]:
        with self._lock:
            if not self.enabled:
                return None
            if store == "result":
                entry = self._results.get(key)
                if entry is None:
                    self._misses[store] += 1
                    return None
                value, inserted = entry
                if time.monotonic() - inserted > self._result_ttl:
                    self._results.pop(key, None)
                    self._misses[store] += 1
                    return None
                self._hits[store] += 1
                return value
            store_map = {"schema": self._schema, "sql": self._sql, "doc": self._docs}
            value = store_map[store].get(key)
            if value is None:
                self._misses[store] += 1
            else:
                self._hits[store] += 1
            return value

    def _set(self, store: str, key: str, value: Any) -> None:
        if not self.enabled:
            return
        with self._lock:
            if store == "result":
                self._results[key] = (value, time.monotonic())
            elif store == "schema":
                self._schema[key] = value
            elif store == "sql":
                self._sql[key] = value
            elif store == "doc":
                self._docs[key] = value

    # ------------------------------------------------------------------
    def get_schema_selection(self, question: str, candidates_hash: str) -> Optional[str]:
        return self._get("schema", f"{question}|{candidates_hash}")

    def set_schema_selection(self, question: str, candidates_hash: str, table_name: str) -> None:
        self._set("schema", f"{question}|{candidates_hash}", table_name)

    def get_sql(self, question: str, schema_version: str) -> Optional[str]:
        return self._get("sql", f"{question}|{schema_version}")

    def set_sql(self, question: str, schema_version: str, sql: str) -> None:
        self._set("sql", f"{question}|{schema_version}", sql)

    def get_result(self, sql: str, table_name: str, result_hash: str) -> Optional[Any]:
        return self._get("result", f"{sql}|{table_name}|{result_hash}")

    def set_result(self, sql: str, table_name: str, result_hash: str, value: Any) -> None:
        self._set("result", f"{sql}|{table_name}|{result_hash}", value)

    def get_schema_doc(self, table_id: str, version: int) -> Optional[str]:
        return self._get("doc", f"{table_id}:{version}")

    def set_schema_doc(self, table_id: str, version: int, doc: str) -> None:
        self._set("doc", f"{table_id}:{version}", doc)

    # ------------------------------------------------------------------
    def invalidate_table(self, table_id: str) -> None:
        """Drop every cache entry mentioning a table (called on version bump)."""
        with self._lock:

            def mentions(key: object) -> bool:
                # Keys embed table ids as "q?|001,002" or "001:1" (id:version).
                segs = str(key).replace("|", ",").replace(":", ",").split(",")
                return table_id in segs

            for store in (self._schema, self._sql, self._docs):
                for key in [k for k in store.keys() if mentions(k)]:
                    store.pop(key, None)
            for key in [k for k in self._results.keys() if mentions(k)]:
                self._results.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._schema.clear()
            self._sql.clear()
            self._docs.clear()
            self._results.clear()

    def stats(self) -> Dict[str, Dict[str, int]]:
        with self._lock:
            return {
                store: {"hits": self._hits[store], "misses": self._misses[store]}
                for store in self._hits
            }

    def cache_hit_ratio(self) -> float:
        with self._lock:
            hits = sum(self._hits.values())
            misses = sum(self._misses.values())
            return hits / (hits + misses) if (hits + misses) else 0.0
