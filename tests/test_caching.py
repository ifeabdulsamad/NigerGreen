"""Cache manager tests: TTL, invalidation, hit ratio (TRD §9.2)."""
from __future__ import annotations

import time

from cache_manager import CacheManager


def test_schema_selection_roundtrip():
    c = CacheManager(enabled=True)
    c.set_schema_selection("q?", "abc", "csv_001")
    assert c.get_schema_selection("q?", "abc") == "csv_001"
    assert c.get_schema_selection("q?", "zzz") is None


def test_ttl_expiry():
    c = CacheManager(enabled=True, schema_ttl_s=1)
    c.set_schema_selection("q", "k", "t1")
    assert c.get_schema_selection("q", "k") == "t1"
    time.sleep(1.1)
    assert c.get_schema_selection("q", "k") is None


def test_result_ttl_on_access():
    c = CacheManager(enabled=True, result_ttl_s=1)
    c.set_result("SELECT 1", "t", "sig", {"x": 1})
    assert c.get_result("SELECT 1", "t", "sig") == {"x": 1}
    time.sleep(1.1)
    assert c.get_result("SELECT 1", "t", "sig") is None


def test_lru_eviction():
    c = CacheManager(enabled=True, max_entries=2)
    c.set_schema_doc("a", 1, "doc-a")
    c.set_schema_doc("b", 1, "doc-b")
    c.set_schema_doc("c", 1, "doc-c")
    assert c.get_schema_doc("a", 1) is None  # evicted
    assert c.get_schema_doc("c", 1) == "doc-c"


def test_invalidate_table_clears_related_entries():
    c = CacheManager(enabled=True)
    # Keys embed table ids exactly as sql_engine builds them.
    c.set_schema_selection("co2 question", "001,002", "001")
    c.set_sql("co2 question", "001:1", "SELECT 1")
    c.set_schema_doc("001", 1, "doc")
    c.invalidate_table("001")
    assert c.get_schema_selection("co2 question", "001,002") is None
    assert c.get_sql("co2 question", "001:1") is None
    assert c.get_schema_doc("001", 1) is None
    # Unrelated entries survive.
    c.set_sql("other question", "002:1", "SELECT 2")
    c.invalidate_table("001")
    assert c.get_sql("other question", "002:1") == "SELECT 2"


def test_disabled_cache_stores_nothing():
    c = CacheManager(enabled=False)
    c.set_sql("q", "v", "SELECT 1")
    assert c.get_sql("q", "v") is None


def test_hit_ratio_tracks():
    c = CacheManager(enabled=True)
    c.set_result("s", "t", "sig", 1)
    c.get_result("s", "t", "sig")  # hit
    c.get_result("s", "t", "nope")  # miss
    ratio = c.cache_hit_ratio()
    assert 0.0 < ratio < 1.0
