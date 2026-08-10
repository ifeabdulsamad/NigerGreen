# NaijaGreen Chat — TRD v2.0 (implemented spec, condensed)

The full authoritative TRD v2.0 lives with the project owner. This file is
the implementation reference — a condensed contract that the code follows.

## Purpose

Streamlit app where users upload sustainability CSVs; the system infers
schemas and answers natural-language questions via a two-stage LLM pipeline
(DeepSeek via LiteLLM): schema selection -> SQL generation -> validated
execution -> NL summary.

## Contract (what the code must do)

| Area | Spec |
|---|---|
| Stage 1 model | `deepseek/deepseek-chat`, temp 0.1, max 200 tok, reply `<table>` or `<NONE>` |
| Stage 2 model | `deepseek/deepseek-chat`, temp 0.1, max 500 tok, pure SQL |
| Fallback model | `deepseek/deepseek-reasoner` |
| SQL safety | sqlparse AST: single SELECT, whitelisted table only, no PRAGMA/ATTACH/DML, 5s timeout |
| Table naming | `csv_{table_id}_{sanitized}` — lowercase, `_`-collapse, 63-char cap, hash on collision |
| Schema registry | versioned rows, checksum (SHA256), thematic tags, columns_json with units/null/categorical |
| Caching | schema 30min, sql 1h, results 5min (in-memory), invalidated on version bump |
| Errors | E001 no key -> demo mode; E002/E003 retry+fallback; E004 refuse; E005 retry w/o LIMIT; E006 empty; E007/E008 timeout/rate-limit backoff |
| Uploads | .csv only, ≤20MB, header required, encoding detected (chardet), duplicate columns rejected |
| Demo mode | rule-based schema scoring + 10 SQL templates, clearly flagged in UI |
| Latency | end-to-end <5s cold, <1.5s cached; 10 concurrent users |

## File structure (implemented)

```
app.py  sql_engine.py  schema_registry.py  database.py
config.py  logger.py  cache_manager.py
prompts/{schema_selection,sql_generation}.txt
requirements.txt  .env.example  Dockerfile  docker-compose.yml
.streamlit/{config,secrets}.toml   data/*.csv   tests/ (+fixtures)   docs/
```

## Decision records (TRD §13.3)

- sqlparse for validation (handles subqueries/aliases; regex alone is unsafe)
- structured logging early (structlog JSON; trace fields question_hash/sql_hash)
- cache schemas+queries (cuts API cost >60%, interactive latency)
- SQLite WAL (concurrent reads during schema updates, zero infra)
