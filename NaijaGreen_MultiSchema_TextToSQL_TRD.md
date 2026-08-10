# NaijaGreen Chat: Multi-Schema Text-to-SQL Engine
## Technical Requirements Document (TRD)

**Version:** 1.0
**Date:** August 2026
**Status:** Draft
**Author:** NaijaGreen Engineering Team

---

## Table of Contents

1. [Document Purpose](#1-document-purpose)
2. [System Architecture](#2-system-architecture)
3. [Technology Stack](#3-technology-stack)
4. [Data Models & Schemas](#4-data-models--schemas)
5. [API Specifications](#5-api-specifications)
6. [Implementation Details](#6-implementation-details)
7. [Error Handling & Resilience](#7-error-handling--resilience)
8. [Security Requirements](#8-security-requirements)
9. [Performance Benchmarks](#9-performance-benchmarks)
10. [Testing Strategy](#10-testing-strategy)
11. [Deployment Architecture](#11-deployment-architecture)
12. [Appendix](#12-appendix)

---

## 1. Document Purpose

This TRD translates the NaijaGreen Chat PRD into actionable technical specifications. It serves as the single source of truth for engineers implementing the multi-schema text-to-SQL engine.

**Scope:** Covers the complete technical implementation from CSV ingestion to user-facing query results.
**Out of Scope:** Data collection/curation, model training, mobile app development.

---

## 2. System Architecture

### 2.1 High-Level Architecture

```
+--------------------------------------------------------------------------+
|                           NaijaGreen Chat System                          |
+--------------------------------------------------------------------------+
|                                                                          |
|  +------------------+     +------------------+     +------------------+ |
|  |   Streamlit UI   |     |   Streamlit UI   |     |   Streamlit UI   | |
|  |   (app.py)       |<--->|   (app.py)       |<--->|   (app.py)       | |
|  +--------+---------+     +--------+---------+     +--------+---------+ |
|           |                        |                        |            |
|           v                        v                        v            |
|  +---------------------------------------------------------------+      |
|  |                    TextToSQLEngine (sql_engine.py)             |      |
|  |  +------------------+     +------------------+                |      |
|  |  | Stage 1: Schema  |     | Stage 2: SQL     |                |      |
|  |  | Selection        |---->| Generation       |                |      |
|  |  | (LLM call)       |     | (LLM call)       |                |      |
|  |  +------------------+     +------------------+                |      |
|  +-------------------------------^-------------------------------+      |
|                                  |                                       |
|                                  v                                       |
|  +---------------------------------------------------------------+      |
|  |                    SchemaRegistry (schema_registry.py)           |      |
|  |  +------------------+     +------------------+                |      |
|  |  | Schema Inference |     | Schema Storage   |                |      |
|  |  | (Auto-generate)  |     | (SQLite table)   |                |      |
|  |  +------------------+     +------------------+                |      |
|  +---------------------------------------------------------------+      |
|                                  |                                       |
|                                  v                                       |
|  +---------------------------------------------------------------+      |
|  |                    Database Layer (database.py)                  |      |
|  |  +------------------+     +------------------+                |      |
|  |  | SQLite Engine    |     | Query Executor   |                |      |
|  |  | (Multi-table)    |     | (Validation)     |                |      |
|  |  +------------------+     +------------------+                |      |
|  +---------------------------------------------------------------+      |
|                                  |                                       |
|                                  v                                       |
|  +---------------------------------------------------------------+      |
|  |                    LiteLLM + Groq Provider                       |      |
|  |  Schema Model: groq/llama-3.1-70b-versatile                    |      |
|  |  SQL Model:    groq/llama-3.1-8b-instant                       |      |
|  +---------------------------------------------------------------+      |
|                                                                          |
+--------------------------------------------------------------------------+
```

### 2.2 Component Breakdown

| Component | File | Responsibility |
|-----------|------|---------------|
| **UI Layer** | `app.py` | Streamlit interface, chat history, visualization |
| **Query Engine** | `sql_engine.py` | Two-stage LLM pipeline, prompt engineering, result formatting |
| **Schema Registry** | `schema_registry.py` | Auto-inference, schema documentation generation, registry CRUD |
| **Database Layer** | `database.py` | SQLite connection, multi-table management, query execution |
| **Config** | `config.py` | Environment variables, model selection, thresholds |

### 2.3 Data Flow

```
CSV File -> Schema Inference -> Schema Registry -> LLM Schema Selection
                                                    |
User Question -> Schema Retrieval -> LLM SQL Generation -> Validation
                                                              |
                                                      Query Execution
                                                              |
                                                      Result Formatting -> UI
```

---

## 3. Technology Stack

### 3.1 Core Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `python` | >=3.9 | Runtime |
| `pandas` | >=2.0.0 | Data manipulation, CSV reading |
| `litellm` | >=1.40.0 | Unified LLM API wrapper |
| `streamlit` | >=1.30.0 | Web UI framework |
| `plotly` | >=5.18.0 | Interactive charts |
| `sqlite3` | Built-in | Database engine |
| `python-dotenv` | >=1.0.0 | Environment management |

### 3.2 LLM Provider

| Aspect | Specification |
|--------|--------------|
| **Provider** | Groq via LiteLLM |
| **Schema Selection Model** | `groq/llama-3.1-70b-versatile` |
| **SQL Generation Model** | `groq/llama-3.1-8b-instant` |
| **Fallback Model** | `groq/mixtral-8x7b-32768` |
| **API Endpoint** | `https://api.groq.com/openai/v1` |
| **Max Tokens (Schema)** | 100 |
| **Max Tokens (SQL)** | 500 |
| **Temperature** | 0.1 (both stages) |

### 3.3 Infrastructure

| Layer | Technology |
|-------|-----------|
| **Runtime** | Local Python / Docker |
| **Database** | SQLite (file-based) |
| **File Storage** | Local filesystem (`data/` directory) |
| **Secrets Management** | `.streamlit/secrets.toml` or environment variables |

---

## 4. Data Models & Schemas

### 4.1 Schema Registry Table

```sql
CREATE TABLE schema_registry (
    table_id        TEXT PRIMARY KEY,
    table_name      TEXT NOT NULL,
    file_name       TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    row_count       INTEGER NOT NULL,
    column_count    INTEGER NOT NULL,
    schema_doc      TEXT NOT NULL,
    columns_json    TEXT NOT NULL,
    thematic_tags   TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Indexes:**
```sql
CREATE INDEX idx_schema_thematic ON schema_registry(thematic_tags);
CREATE INDEX idx_schema_filename ON schema_registry(file_name);
```

### 4.2 columns_json Structure

```json
[
  {
    "name": "co2_emissions_tons",
    "dtype": "float64",
    "sample_values": [125000.5, 98000.0, 142300.2],
    "min": 45000.0,
    "max": 200000.0,
    "unique_count": 37,
    "null_count": 0,
    "description": "Annual CO2 emissions in metric tons"
  }
]
```

### 4.3 Dynamic Data Tables

Each CSV becomes a SQLite table with the naming convention:

```
csv_{table_id}_{sanitized_filename}
```

Example: `csv_001_lagos_emissions_2020`

**Table Naming Rules:**
- Strip file extension
- Replace non-alphanumeric with underscore
- Truncate to 50 characters
- Prefix with `csv_{id}_`

### 4.4 Chat History (Optional)

```sql
CREATE TABLE chat_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    question        TEXT NOT NULL,
    selected_table  TEXT,
    generated_sql   TEXT,
    execution_time  REAL,
    row_count       INTEGER,
    error_message   TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 5. API Specifications

### 5.1 TextToSQLEngine Class

```python
class TextToSQLEngine:
    def __init__(
        self,
        api_key: Optional[str] = None,
        schema_model: str = "groq/llama-3.1-70b-versatile",
        sql_model: str = "groq/llama-3.1-8b-instant",
        demo_mode: bool = False
    ) -> None

    def select_schema(
        self,
        question: str,
        candidate_schemas: List[Tuple[str, str]]
    ) -> str
    # Stage 1: Select the most relevant table from candidates.
    # Returns: table_name (str)
    # Raises: SchemaSelectionError

    def generate_sql(
        self,
        question: str,
        schema_doc: str,
        table_name: str
    ) -> str
    # Stage 2: Generate SQLite SELECT query.
    # Returns: sql (str)
    # Raises: SQLGenerationError

    def execute_query(
        self,
        sql: str,
        table_name: str
    ) -> pd.DataFrame
    # Execute validated SQL against SQLite.
    # Returns: DataFrame
    # Raises: QueryExecutionError, ValidationError

    def answer_question(
        self,
        question: str
    ) -> Dict[str, Any]
    # End-to-end pipeline: question -> results.
    # Returns: dict with question, selected_table, sql, results, execution_time_ms, error
```

### 5.2 SchemaRegistry Class

```python
class SchemaRegistry:
    def __init__(self, db_path: str = "naijagreen.db") -> None

    def infer_schema(self, csv_path: str, table_id: Optional[str] = None) -> Dict[str, Any]
    # Auto-infer schema from CSV file.

    def register_csv(self, csv_path: str, thematic_tags: Optional[List[str]] = None) -> str
    # Full pipeline: CSV -> SQLite table + schema registry entry.
    # Returns: table_id

    def get_schema_doc(self, table_id: str) -> str
    def get_all_schemas(self) -> List[Tuple[str, str]]
    def search_schemas(self, query: str) -> List[Tuple[str, str, float]]
    def delete_schema(self, table_id: str) -> bool
```

### 5.3 DatabaseManager Class

```python
class DatabaseManager:
    def __init__(self, db_path: str = "naijagreen.db") -> None

    def create_table_from_df(self, df: pd.DataFrame, table_name: str, if_exists: str = "replace") -> None
    def execute_query(self, sql: str) -> pd.DataFrame
    def validate_sql(self, sql: str, allowed_tables: List[str]) -> bool
    def get_table_preview(self, table_name: str, n: int = 5) -> pd.DataFrame
    def list_tables(self) -> List[str]
```

---

## 6. Implementation Details

### 6.1 Schema Inference Algorithm

```python
def infer_schema(csv_path: str) -> Dict:
    df = pd.read_csv(csv_path)

    # 1. Detect dtypes with override for categorical
    dtypes = {}
    for col in df.columns:
        if df[col].dtype == 'object' and df[col].nunique() / len(df) < 0.1:
            dtypes[col] = 'categorical'
        else:
            dtypes[col] = str(df[col].dtype)

    # 2. Generate column descriptions
    column_descriptions = []
    for col in df.columns:
        desc = {
            "name": col,
            "dtype": dtypes[col],
            "sample_values": df[col].dropna().head(3).tolist(),
            "unique_count": df[col].nunique(),
            "null_count": df[col].isna().sum()
        }
        if dtypes[col] in ['int64', 'float64']:
            desc["min"] = df[col].min()
            desc["max"] = df[col].max()
        column_descriptions.append(desc)

    # 3. Generate thematic tags (simple keyword extraction)
    filename = Path(csv_path).stem.lower()
    tags = extract_thematic_tags(filename, df.columns.tolist())

    # 4. Build schema_doc
    schema_doc = build_schema_doc(df, column_descriptions, csv_path)

    return {
        "row_count": len(df),
        "column_count": len(df.columns),
        "schema_doc": schema_doc,
        "columns_json": json.dumps(column_descriptions),
        "thematic_tags": json.dumps(tags)
    }
```

### 6.2 Schema Document Template

```python
def build_schema_doc(df, columns, csv_path):
    filename = Path(csv_path).name

    doc = f"TABLE: {table_name}\n"
    doc += f"SOURCE FILE: {filename}\n"
    doc += f"ROWS: {len(df)}\n"
    doc += f"COLUMNS: {len(df.columns)}\n\n"
    doc += "COLUMN DETAILS:\n"

    for col in columns:
        doc += f"  - {col['name']} ({col['dtype']})"
        if 'min' in col:
            doc += f", range: [{col['min']:.2f} to {col['max']:.2f}]"
        doc += f", {col['unique_count']} unique values"
        doc += f", samples: {col['sample_values'][:3]}\n"

    doc += "\nSAMPLE DATA (first 3 rows):\n"
    doc += df.head(3).to_string(index=False)

    return doc
```

### 6.3 Two-Stage LLM Prompts

**Stage 1: Schema Selection**

```
SYSTEM: You are a database schema matching expert. Given a user's question
and a list of available database tables with their schemas, identify the
SINGLE table that best contains the data needed to answer the question.

Rules:
- Reply with ONLY the table name, nothing else
- If no table seems relevant, reply with "NONE"
- Do not explain your reasoning
- Table names are case-sensitive

USER: AVAILABLE TABLES:
{schemas_text}

USER QUESTION: {question}

Which table should be queried? Reply with just the table name.
```

**Stage 2: SQL Generation**

```
SYSTEM: You are an expert SQLite query generator. Given a table schema and
a natural language question, write a valid, efficient SQLite SELECT query.

Rules:
- Return ONLY the raw SQL query, no markdown formatting, no explanations
- Use only the table and columns described in the schema
- Use proper SQLite syntax
- Use parameterized queries where appropriate
- For aggregations, include GROUP BY clauses
- Limit results to 100 rows unless explicitly asked for more
- If the question cannot be answered with the schema, return
  "SELECT 'Cannot answer with available data' as error;"

SCHEMA:
{schema_doc}

USER: Q: {question}
A:
```

### 6.4 SQL Validation

```python
def validate_sql(sql: str, allowed_table: str) -> Tuple[bool, str]:
    # 1. Check for DML/DDL (only SELECT allowed)
    forbidden_keywords = ['INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ALTER']
    sql_upper = sql.upper()
    for kw in forbidden_keywords:
        if kw in sql_upper:
            return False, f"Forbidden keyword detected: {kw}"

    # 2. Check table references
    table_pattern = r'(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)'
    referenced_tables = re.findall(table_pattern, sql_upper)

    if allowed_table.upper() not in [t.upper() for t in referenced_tables]:
        return False, f"SQL does not reference expected table: {allowed_table}"

    # 3. Basic syntax check
    if not sql.strip().upper().startswith('SELECT'):
        return False, "Query must start with SELECT"

    return True, "Valid"
```

### 6.5 Candidate Schema Filtering

To reduce token usage in Stage 1, implement pre-filtering:

```python
def get_candidate_schemas(question: str, all_schemas: List, top_k: int = 5) -> List:
    question_tokens = set(question.lower().split())
    scored = []

    for table_name, schema_doc, tags in all_schemas:
        score = 0
        # Tag matching
        for tag in json.loads(tags or '[]'):
            if tag.lower() in question.lower():
                score += 3

        # Column name matching
        for token in question_tokens:
            if token in schema_doc.lower():
                score += 1

        # Filename matching
        if token in table_name.lower():
            score += 2

        scored.append((table_name, schema_doc, score))

    scored.sort(key=lambda x: x[2], reverse=True)
    return scored[:top_k]
```

---

## 7. Error Handling & Resilience

### 7.1 Error Taxonomy

| Error Code | Description | Recovery Strategy |
|------------|-------------|-------------------|
| `E001` | No API key configured | Switch to demo mode, show message |
| `E002` | Schema selection failed | Return "No relevant data found" |
| `E003` | SQL generation failed | Retry once with fallback model |
| `E004` | SQL validation failed | Log error, return explanation |
| `E005` | Query execution failed | Check syntax, suggest rephrasing |
| `E006` | Empty results | Suggest broader query |
| `E007` | LLM timeout | Return "Service temporarily unavailable" |
| `E008` | Rate limit exceeded | Queue request, show retry timer |

### 7.2 Retry Logic

```python
@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=10))
def call_llm_with_retry(model: str, messages: List, **kwargs):
    return completion(model=model, messages=messages, **kwargs)
```

### 7.3 Demo Mode

When `GROQ_API_KEY` is missing:
- Show banner: "Running in demo mode. Add GROQ_API_KEY for full functionality."
- Use rule-based SQL generation for common patterns
- Pre-computed schema selection for sample questions

---

## 8. Security Requirements

### 8.1 SQL Injection Prevention

| Layer | Measure |
|-------|---------|
| **Input Validation** | Regex whitelist for allowed characters in questions |
| **SQL Validation** | Parse AST, reject non-SELECT statements |
| **Table Whitelist** | Only allow queries against registered tables |
| **Parameterization** | Use parameterized queries for user-provided values |

### 8.2 API Key Management

```python
# config.py
import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY") or st.secrets.get("GROQ_API_KEY")
DEMO_MODE = not GROQ_API_KEY

# Never log the full key
LOG_KEY = GROQ_API_KEY[:8] + "..." if GROQ_API_KEY else None
```

### 8.3 Data Privacy

- All data stored locally in SQLite
- No user queries sent to third parties except Groq API
- Chat history optional and local-only
- No PII expected in sustainability datasets

---

## 9. Performance Benchmarks

### 9.1 Latency Targets

| Operation | Target | Maximum |
|-----------|--------|---------|
| Schema inference (per CSV) | <2s | <5s |
| Schema selection (LLM call) | <500ms | <2s |
| SQL generation (LLM call) | <300ms | <1s |
| Query execution | <100ms | <500ms |
| End-to-end (cached schema) | <2s | <5s |
| End-to-end (full pipeline) | <5s | <10s |

### 9.2 Throughput Targets

| Metric | Target |
|--------|--------|
| Concurrent users | 10 |
| Queries per minute | 60 |
| CSVs in registry | 100+ |
| Total rows across tables | 1M+ |

### 9.3 Cost Targets

| Metric | Target |
|--------|--------|
| Cost per query | <$0.001 |
| Daily cost (100 queries) | <$0.10 |
| Monthly cost (3K queries) | <$3.00 |

---

## 10. Testing Strategy

### 10.1 Unit Tests

```python
# tests/test_schema_registry.py
def test_infer_schema_basic():
    registry = SchemaRegistry(":memory:")
    result = registry.infer_schema("test_data/emissions.csv")
    assert result["row_count"] > 0
    assert result["column_count"] == 5
    assert "co2" in result["schema_doc"].lower()

def test_sql_validation_blocks_ddl():
    db = DatabaseManager(":memory:")
    valid, msg = db.validate_sql("DROP TABLE users", ["environment_data"])
    assert not valid
    assert "DROP" in msg
```

### 10.2 Integration Tests

```python
# tests/test_pipeline.py
def test_end_to_end_pipeline():
    engine = TextToSQLEngine(demo_mode=True)
    result = engine.answer_question("What was Lagos CO2 in 2020?")
    assert result["selected_table"] is not None
    assert result["sql"].startswith("SELECT")
    assert len(result["results"]) > 0
```

### 10.3 Test Data

Create `tests/fixtures/` with:
- `emissions_lagos.csv` (50 rows, 5 columns)
- `energy_national.csv` (36 rows, 4 columns)
- `water_quality_kano.csv` (100 rows, 6 columns)

### 10.4 LLM Evaluation

| Test Case | Expected Table | Expected SQL Pattern |
|-----------|---------------|---------------------|
| "Lagos CO2 2020" | `csv_*_lagos*` | `SELECT ... WHERE year = 2020` |
| "Highest energy state" | `csv_*_energy*` | `SELECT ... ORDER BY ... DESC LIMIT 1` |
| "Average water pH" | `csv_*_water*` | `SELECT AVG(ph) ...` |

---

## 11. Deployment Architecture

### 11.1 Local Development

```bash
# Clone and setup
git clone <repo>
cd naijagreen-chat
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with GROQ_API_KEY

# Run
streamlit run app.py
```

### 11.2 Docker Deployment

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

### 11.3 Environment Configuration

```toml
# .streamlit/secrets.toml
GROQ_API_KEY = "gsk_..."
SCHEMA_MODEL = "groq/llama-3.1-70b-versatile"
SQL_MODEL = "groq/llama-3.1-8b-instant"
MAX_CANDIDATE_SCHEMAS = 5
DEMO_MODE = false
```

```bash
# .env
GROQ_API_KEY=gsk_...
DB_PATH=naijagreen.db
DATA_DIR=./data
LOG_LEVEL=INFO
```

---

## 12. Appendix

### 12.1 File Structure

```
naijagreen-chat/
|-- app.py                      # Streamlit UI
|-- sql_engine.py              # Two-stage LLM pipeline
|-- schema_registry.py          # Schema inference + registry
|-- database.py                 # SQLite utilities
|-- config.py                  # Configuration management
|-- requirements.txt           # Dependencies
|-- .env.example               # Environment template
|-- .streamlit/
|   |-- secrets.toml           # Streamlit secrets
|   |-- config.toml            # Streamlit config
|-- data/                      # CSV data files
|   |-- emissions_lagos.csv
|   |-- energy_national.csv
|   |-- water_quality_kano.csv
|   |-- ...
|-- tests/
|   |-- test_schema_registry.py
|   |-- test_sql_engine.py
|   |-- test_database.py
|   |-- fixtures/
|       |-- emissions_lagos.csv
|       |-- energy_national.csv
|       |-- water_quality_kano.csv
|-- docs/
    |-- PRD.md                 # Product Requirements Document
    |-- TRD.md                 # This document
    |-- ARCHITECTURE.md        # Architecture decision records
```

### 12.2 Glossary

| Term | Definition |
|------|-----------|
| **Schema** | Structure and metadata of a database table |
| **Schema Registry** | Central catalog of all available table schemas |
| **Schema Selection** | LLM stage that picks the relevant table |
| **SQL Generation** | LLM stage that writes the database query |
| **Two-Stage Pipeline** | Sequential schema selection then SQL generation |
| **Schema Doc** | Human/LLM-readable description of a table |
| **Candidate Filtering** | Pre-LLM keyword matching to reduce schema options |
| **Demo Mode** | Fallback operation without API keys |

### 12.3 Decision Records

| Decision | Rationale |
|----------|-----------|
| SQLite over PostgreSQL | Zero-config, file-based, sufficient for 100+ tables |
| LiteLLM over direct Groq | Future-proofing, easy provider swaps |
| Two models (70B + 8B) | Cost optimization: smart task gets big model, simple task gets small |
| Streamlit over FastAPI | Rapid prototyping, built-in widgets, Python-native |
| Auto-schema inference | Scales to 100+ CSVs without manual documentation |
| Keyword pre-filtering | Reduces LLM token usage by 80%+ |

### 12.4 Migration Notes

From single-table to multi-schema:
- `database.py`: Add multi-table support, table listing
- `sql_engine.py`: Add `select_schema()` method, update `generate_sql()` signature
- `schema_registry.py`: New file, handles inference and registry
- `app.py`: Add schema upload UI, registry viewer
- No changes to LLM provider layer (LiteLLM remains)

---

**End of Document**

*This TRD is a living document. Update as implementation reveals new requirements or constraints.*
