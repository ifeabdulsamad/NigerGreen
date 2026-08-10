# NaijaGreen Chat — Architecture

## High level

```
+------------------+     +------------------+     +------------------+
|  Streamlit UI    |<--->|  Streamlit UI    |<--->|  Streamlit UI    |
|  (app.py)        |     |  (app.py)        |     |  (app.py)        |
+--------+---------+     +--------+---------+     +--------+---------+
         |                        |                        |
         v                        v                        v
+---------------------------------------------------------------+
|                    TextToSQLEngine (sql_engine.py)           |
|  +------------------+     +------------------+              |
|  | Stage 1: Schema  |---->| Stage 2: SQL     |              |
|  | Selection        |     | Generation       |              |
|  +------------------+     +------------------+              |
+-------------------------------^-----------------------------+
                                |
                                v
+---------------------------------------------------------------+
|                    SchemaRegistry (schema_registry.py)       |
|  +------------------+     +------------------+              |
|  | Schema Inference |     | Schema Storage   |              |
|  | (auto-generate)  |     | (SQLite table)   |              |
|  +------------------+     +------------------+              |
+---------------------------------------------------------------+
                                |
                                v
+---------------------------------------------------------------+
|                    Database Layer (database.py)              |
|  +------------------+     +------------------+              |
|  | SQLite Engine    |     | Query Executor   |              |
|  | (multi-table)    |     | (validation)     |              |
|  +------------------+     +------------------+              |
+---------------------------------------------------------------+
                                |
                                v
+---------------------------------------------------------------+
|                    LiteLLM + DeepSeek Provider                |
|  Schema Model: deepseek/deepseek-chat                      |
|  SQL Model:    deepseek/deepseek-chat                      |
|  Fallback:     deepseek/deepseek-reasoner                  |
+---------------------------------------------------------------+
```

## Data flow

```
CSV file -> validation -> schema inference -> schema_registry (versioned)
                                                      |
User question -> input validation -> cache lookup? -no-> keyword pre-filter
        |                                                    |
        |<------------------ cache hit <---------------------
        v
Stage 1 (LLM): pick table -> Stage 2 (LLM): write SQL
        |
        v
AST validation (sqlparse) -> execution (SQLite, WAL, timeout)
        |
        v
Result cache (TTL) -> NL summary -> UI (table + chart + SQL)
```

## Cross-cutting

- **Validation**: sqlparse AST — single SELECT only, table whitelist,
  forbidden keywords/fragments (PRAGMA/ATTACH/DML/sqlite_*), 5s progress
  handler deadline.
- **Caching**: cachetools TTLCache (schema 30m, sql 1h) + LRU results (5m),
  invalidated per-table on version bump.
- **Errors**: E001–E010 taxonomy with retries (exp backoff + jitter),
  fallback model, and template-SQL recovery.
- **Demo mode**: no API key needed; rule-based schema selection (keyword
  overlap) and ~10 SQL templates (total/year, average, top-N, show all…).
