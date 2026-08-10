# NaijaGreen Chat: Multi-Schema Text-to-SQL Engine
## Product Requirements Document (PRD)

**Version:** 1.0  
**Date:** August 4, 2026  
**Status:** Draft  
**Author:** Product Team  

---

## 1. Executive Summary

NaijaGreen Chat is an intelligent natural-language-to-SQL interface designed to query 100+ heterogeneous CSV datasets related to Nigerian sustainability, climate, and environmental metrics. Unlike traditional single-table text-to-SQL tools, this engine features a **multi-schema architecture** that automatically infers, registers, and selects the correct data source before generating and executing SQL queries.

The product enables non-technical stakeholders (policymakers, journalists, researchers, and citizens) to ask plain English questions like *"What was Lagos CO2 in 2020?"* and receive accurate, visualized answers without writing SQL or knowing which dataset contains the data.

---

## 2. Goals and Objectives

### 2.1 Primary Goals
- **Democratize data access:** Allow non-technical users to query 100+ CSV datasets using natural language.
- **Zero-configuration schema handling:** Automatically infer, document, and register schemas for any uploaded CSV without manual intervention.
- **Accurate multi-table selection:** Achieve >90% accuracy in selecting the correct table from 100+ candidates given a natural language question.
- **End-to-end query pipeline:** Handle the full flow from question input to validated SQL execution to formatted results with charts.

### 2.2 Secondary Goals
- Support thematic grouping of datasets (e.g., emissions, energy, water quality, agriculture).
- Provide a transparent, debuggable pipeline so users can see which table was selected and why.
- Enable extensibility for future API integrations beyond CSV files.

### 2.3 Success Criteria
| Metric | Target |
|--------|--------|
| Schema selection accuracy | >= 90% |
| SQL generation accuracy (valid + correct) | >= 85% |
| Query response time (end-to-end) | < 5 seconds |
| User query success rate (no errors) | >= 80% |
| Supported CSV count at launch | 100+ |

---

## 3. Target Users and Personas

### 3.1 Primary Personas

**Persona A: Ada, Policy Analyst (Ministry of Environment)**
- Needs quick answers from disparate datasets to draft policy briefs.
- Does not know SQL. Needs confidence in data source selection.
- Wants exportable charts for presentations.

**Persona B: Chidi, Investigative Journalist**
- Asks exploratory questions across multiple datasets.
- Needs transparency (which CSV, which rows) for fact-checking.
- Values speed and accuracy over advanced analytics.

**Persona C: Dr. Emeka, Climate Researcher**
- Asks precise, technical questions with filters and aggregations.
- Comfortable with data but wants to avoid manual CSV wrangling.
- Needs raw data export for further analysis.

### 3.2 Secondary Personas
- **Citizens:** General public asking simple factual questions.
- **Data Engineers:** Maintainers who upload new CSVs and verify schema inference.

---

## 4. Functional Requirements

### 4.1 Schema Preparation Pipeline (Offline / Batch)

| ID | Requirement | Priority | Acceptance Criteria |
|----|-------------|----------|---------------------|
| F1.1 | The system must accept CSV uploads (10 to 10,000+ rows) and auto-load them into SQLite. | P0 | Any valid CSV uploads without manual schema definition. |
| F1.2 | The system must automatically infer column data types (INTEGER, REAL, TEXT, DATE). | P0 | Correctly identifies numeric vs text vs date columns in >95% of cases. |
| F1.3 | The system must detect null rates, unique value counts, and min/max ranges per column. | P1 | Metadata stored for every column in schema registry. |
| F1.4 | The system must generate a human-readable schema document per table for LLM consumption. | P0 | Document includes table name, source file, row count, column descriptions, sample rows, and value ranges. |
| F1.5 | The system must store all schema metadata in a central `schema_registry` SQLite table. | P0 | Registry queryable and updatable. |
| F1.6 | The system must support re-processing / updating a schema if a CSV is overwritten. | P1 | Existing table dropped and re-created; registry entry updated. |

### 4.2 Query Execution Pipeline (Online / Real-Time)

| ID | Requirement | Priority | Acceptance Criteria |
|----|-------------|----------|---------------------|
| F2.1 | Users must be able to input questions via a natural language text box. | P0 | Free-text input, no structured query language required. |
| F2.2 | The system must perform **Stage 1: Schema Selection** - an LLM must select the most relevant table(s) from the schema registry based on the user question. | P0 | Returns the correct `table_id` in >= 90% of test cases. |
| F2.3 | The system must perform **Stage 2: SQL Generation** - inject the selected table's schema document + user question into an LLM prompt to generate SQLite-compatible SQL. | P0 | Generated SQL is syntactically valid in >= 95% of cases. |
| F2.4 | The system must validate generated SQL before execution (check table existence, prevent destructive operations). | P0 | Blocks DROP, DELETE without WHERE, INSERT, UPDATE. Only SELECT allowed. |
| F2.5 | The system must execute the validated SQL against the correct SQLite table. | P0 | Returns results as a pandas DataFrame. |
| F2.6 | The system must format results into a human-readable summary + data table. | P0 | Summary text + sortable table displayed. |
| F2.7 | The system must auto-generate an appropriate chart (bar, line, pie) based on result shape. | P1 | Chart type chosen heuristically; user can toggle types. |
| F2.8 | The system must expose the selected table name, generated SQL, and schema doc in an expandable "Debug / Transparency" panel. | P1 | Visible to all users for trust and verification. |
| F2.9 | The system must handle schema selection failure gracefully (e.g., "No relevant dataset found" or suggest top-3 candidates). | P1 | Clear error message + fallback suggestions. |
| F2.10 | The system must handle SQL execution errors gracefully (syntax errors, missing columns) and surface them to the user. | P1 | Error message explains what went wrong without exposing internal stack traces. |

### 4.3 User Interface Requirements

| ID | Requirement | Priority | Acceptance Criteria |
|----|-------------|----------|---------------------|
| F3.1 | Provide a Streamlit-based web UI with a clean, single-page layout. | P0 | App runs locally and is deployable to Streamlit Cloud. |
| F3.2 | Display a sidebar showing all loaded datasets with row counts and topics. | P1 | Clicking a dataset shows its schema doc preview. |
| F3.3 | Main panel: prominent question input box with "Ask" button. | P0 | Enter key or button triggers query. |
| F3.4 | Results area: summary text, data table, and chart stacked vertically. | P0 | Responsive layout; chart resizes with window. |
| F3.5 | Debug panel: collapsible section showing schema selection reasoning, generated SQL, and execution time. | P1 | Hidden by default, expandable on click. |
| F3.6 | Support CSV upload via UI for new datasets (admin/guarded feature). | P2 | Uploaded CSVs auto-processed through schema pipeline. |
| F3.7 | Support dark/light mode toggle. | P3 | Theme persists across sessions. |

---

## 5. Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NF1 | **Performance:** End-to-end query latency (question to results) must be under 5 seconds on standard hardware. | < 5s |
| NF2 | **Scalability:** Schema registry must support 500+ tables without degradation in selection accuracy. | 500+ tables |
| NF3 | **Reliability:** SQL execution must be sandboxed; no write operations allowed via generated queries. | 100% enforcement |
| NF4 | **Security:** API keys (LLM) must be stored securely (env vars, not hardcoded). | No keys in source |
| NF5 | **Portability:** System must run locally with Python + SQLite; no external DB required. | Local-first |
| NF6 | **Extensibility:** Architecture must allow swapping LLM providers (OpenAI, Anthropic, local models). | Pluggable LLM backend |
| NF7 | **Maintainability:** Code modularized into `schema_registry.py`, `sql_engine.py`, `database.py`, `app.py`. | Clear separation |

---

## 6. Technical Architecture

### 6.1 High-Level Architecture

```
+------------------+        +-------------------+        +------------------+
|   Streamlit UI   |<------>|   SQL Engine      |<------>|   LLM Provider   |
|   (app.py)       |        |   (sql_engine.py) |        |   (OpenAI/etc.)  |
+------------------+        +-------------------+        +------------------+
         |                           |
         v                           v
+------------------+        +-------------------+        +------------------+
|  Schema Registry |<------>|   SQLite Database  |<------>|   CSV Data Lake  |
| (schema_registry)|        |   (naijagreen.db)  |        |   (data/*.csv)   |
+------------------+        +-------------------+        +------------------+
```

### 6.2 Component Breakdown

**A. Schema Registry (`schema_registry.py`)**
- `infer_schema(csv_path)`: Reads CSV, infers dtypes, computes stats.
- `generate_schema_doc(table_name, df)`: Produces LLM-readable schema description.
- `register_schema(table_id, schema_doc, columns_json)`: Writes to `schema_registry` table.
- `get_all_schemas()`: Returns all schema docs for Stage 1 selection.
- `get_schema(table_id)`: Returns specific schema doc for Stage 2 generation.

**B. SQL Engine (`sql_engine.py`)**
- `stage1_select_schema(question, all_schemas)`: LLM call to pick table.
- `stage2_generate_sql(question, selected_schema)`: LLM call to write SQL.
- `validate_sql(sql)`: Regex / AST check for allowed operations only.
- `execute_sql(sql, table_id)`: Runs against SQLite, returns DataFrame.

**C. Database Layer (`database.py`)**
- `load_csv_to_sqlite(csv_path, table_name)`: Creates/replaces table from CSV.
- `get_connection()`: Returns SQLite connection with proper settings.
- `list_tables()`: Returns all user tables (excludes schema_registry).

**D. UI Layer (`app.py`)**
- Streamlit layout, session state management, file upload handler.
- Result formatting (summary + table + chart).
- Debug panel rendering.

### 6.3 Data Model

**schema_registry table:**
```sql
CREATE TABLE schema_registry (
    table_id TEXT PRIMARY KEY,      -- e.g., "csv_001_emissions"
    table_name TEXT,                -- SQL-safe table name
    file_name TEXT,                 -- Original CSV filename
    row_count INTEGER,
    column_count INTEGER,
    schema_doc TEXT,                -- LLM-readable description
    columns_json TEXT,              -- JSON: [{name, dtype, null_pct, sample_values}]
    topic_tag TEXT,                 -- e.g., "emissions", "energy", "water"
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Dynamic data tables:**
- One table per CSV, named `csv_{NNN}_{topic}` or derived from filename.
- All stored in the same SQLite database (`naijagreen.db`).

### 6.4 Two-Stage LLM Pipeline

**Stage 1: Schema Selection Prompt**
```
You are a data assistant. Below are descriptions of all available datasets.
Based on the user's question, return ONLY the table_id of the most relevant dataset.
If none are relevant, return "NONE".

[schema_doc_1]
[schema_doc_2]
...
[schema_doc_N]

User question: "{question}"

Most relevant table_id:
```

**Stage 2: SQL Generation Prompt**
```
You are a SQLite expert. Given the schema below, write a valid SELECT query
that answers the user's question. Return ONLY the SQL, no explanation.

Schema:
{selected_schema_doc}

User question: "{question}"

SQL:
```

---

## 7. Data Requirements

### 7.1 Input Data
- **Source:** 100+ CSV files covering Nigerian sustainability metrics.
- **Format:** UTF-8 CSV with headers. Mixed delimiters auto-detected (comma, semicolon, tab).
- **Size:** 10 rows to 10,000+ rows per file. Total storage < 500MB.
- **Thematic Coverage:** Emissions (CO2, methane), Energy (generation, consumption, renewables), Water (quality, access), Agriculture (yield, rainfall), Waste, Biodiversity.

### 7.2 Naming Conventions
- Preferred: `{topic}_{location}_{year}.csv` or `{topic}_{location}.csv`
- Examples: `emissions_lagos_2020.csv`, `energy_national.csv`, `water_quality_kano.csv`
- Fallback: System auto-generates `csv_{NNN}_{sanitized_name}` if filenames are non-descriptive.

### 7.3 Data Quality Assumptions
- CSVs have consistent headers in the first row.
- Date columns use recognizable formats (ISO 8601 preferred).
- Numeric columns use consistent decimal separators (period `.`).
- Missing values represented as empty strings or standard null indicators.

---

## 8. User Flows

### 8.1 Happy Path: Successful Query

1. User opens NaijaGreen Chat in browser.
2. User types: *"What was Lagos CO2 in 2020?"*
3. System runs Stage 1: LLM selects `csv_042_lagos_emissions`.
4. System runs Stage 2: LLM generates `SELECT co2_tons FROM csv_042_lagos_emissions WHERE year = 2020 AND location = 'Lagos'`.
5. System validates SQL (safe, read-only).
6. System executes SQL against SQLite.
7. System displays:
   - Summary: "Lagos emitted 2.4 million tons of CO2 in 2020."
   - Data table with the result row.
   - Bar chart showing Lagos vs national average (if query supports comparison).
8. User expands debug panel to see selected table and SQL.

### 8.2 Ambiguous Question Flow

1. User asks: *"Show me pollution data."*
2. Stage 1 returns top-3 candidate tables: `csv_012_air_quality_lagos`, `csv_034_water_pollution_rivers`, `csv_067_soil_contamination_delta`.
3. System asks user to clarify or pick one.
4. User selects `csv_012_air_quality_lagos`.
5. Pipeline continues as happy path.

### 8.3 Error Flow: No Relevant Dataset

1. User asks: *"What is the GDP of Japan?"*
2. Stage 1 returns "NONE".
3. System displays: "I could not find a dataset that matches your question. Available topics include: Emissions, Energy, Water Quality, Agriculture. Try rephrasing or browse datasets in the sidebar."

### 8.4 Admin Flow: Upload New CSV

1. Admin navigates to "Upload Data" section (sidebar).
2. Admin drops `waste_abuja_2023.csv`.
3. System validates file format.
4. System runs schema inference pipeline.
5. New table `csv_101_waste_abuja_2023` created.
6. Schema registry updated with new entry.
7. System confirms: "Successfully loaded 'waste_abuja_2023.csv' (1,240 rows, 8 columns). Ready for queries."

---

## 9. UI/UX Design Notes

### 9.1 Layout
- **Sidebar (25% width):**
  - App title and logo.
  - Dataset explorer: searchable list of all loaded CSVs with row/column counts.
  - Topic filter tabs (Emissions, Energy, Water, Agriculture, All).
  - Upload button (admin-only or password-protected).
  - Settings: LLM API key input, theme toggle.

- **Main Panel (75% width):**
  - Question input bar (sticky top, prominent).
  - Results container (appears after query):
    - Summary card (key insight, large font).
    - Data table (sortable, paginated, max 100 rows shown, download CSV button).
    - Chart card (auto-selected type, toggle between bar/line/pie/table view).
  - Debug drawer (bottom, collapsible).

### 9.2 Visual Style
- Clean, government/NGO-friendly aesthetic (greens, blues, whites).
- Nigerian flag accent colors optional but subtle.
- Charts use accessible color palettes (colorblind-safe).
- Loading states: skeleton screens for table, spinner for LLM calls.

### 9.3 Copy and Tone
- Friendly, authoritative, transparent.
- Avoid technical jargon in user-facing messages.
- Debug panel uses monospace font for SQL and schema docs.

---

## 10. Error Handling and Edge Cases

| Scenario | System Behavior |
|----------|----------------|
| LLM returns invalid table_id | Fallback to fuzzy matching on table names; if still no match, ask user. |
| LLM generates invalid SQL | Catch syntax error, show user the SQL + error, suggest rephrasing. |
| SQL returns empty result set | Display: "No data matches your query. Try broadening your filters." |
| CSV has no headers | Reject upload with clear message; require header row. |
| Duplicate CSV uploaded | Prompt: overwrite, skip, or rename. |
| LLM API unavailable / rate limited | Queue request, show status, fallback to cached schema docs for selection. |
| Question requires JOIN across tables | P2: System attempts multi-table JOIN if schemas are compatible; otherwise informs user. |

---

## 11. Analytics and Success Metrics

### 11.1 Product Metrics
- **Monthly Active Users (MAU):** Target 50+ unique users within 3 months of launch.
- **Query Volume:** Target 500+ questions per month.
- **Success Rate:** % of questions that return a meaningful result (target 80%).

### 11.2 Technical Metrics
- **Schema Selection Accuracy:** Measured via labeled test set of 100 questions (target >= 90%).
- **SQL Validity Rate:** % of generated SQL that parses and executes without error (target >= 95%).
- **End-to-End Latency:** P95 query time < 5 seconds.
- **User Satisfaction:** Post-query thumbs up/down rating (target >= 4.0 / 5.0).

### 11.3 Logging
- Log every query: question, selected table, generated SQL, execution time, success/failure, user rating.
- Anonymous usage analytics (no PII).
- Error logs for LLM failures and SQL syntax errors.

---

## 12. Roadmap and Milestones

### Phase 1: MVP (Weeks 1-2)
- [ ] Schema inference and registry pipeline
- [ ] Two-stage LLM pipeline (selection + SQL generation)
- [ ] Basic Streamlit UI with question input and results table
- [ ] SQLite database with 5-10 sample CSVs for testing
- [ ] SQL validation and read-only enforcement

### Phase 2: Alpha (Weeks 3-4)
- [ ] Load 50+ real CSVs
- [ ] Auto-chart generation
- [ ] Debug / transparency panel
- [ ] Sidebar dataset explorer
- [ ] Error handling and graceful fallbacks

### Phase 3: Beta (Weeks 5-6)
- [ ] Scale to 100+ CSVs
- [ ] Thematic topic tags and filtering
- [ ] CSV upload via UI
- [ ] Performance optimization (schema caching, query batching)
- [ ] User feedback mechanism (thumbs up/down)

### Phase 4: Launch (Week 7+)
- [ ] Deploy to Streamlit Cloud or VPS
- [ ] Documentation and user guide
- [ ] Analytics dashboard for admins
- [ ] Community feedback loop for continuous improvement

---

## 13. Risks and Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| LLM schema selection fails on ambiguous questions | High | Medium | Implement top-k retrieval + user clarification dialog. |
| LLM hallucinates column names or table names | High | Medium | Strict SQL validation against actual schema; retry with corrected prompt. |
| 100+ schemas exceed LLM context window | High | Medium | Pre-filter schemas by topic tag or keyword embedding before Stage 1. |
| CSV data quality is poor (inconsistent headers, encoding issues) | Medium | High | Robust CSV parser with encoding detection; reject low-quality files with clear errors. |
| LLM API costs become prohibitive at scale | Medium | Low | Cache schema selections; use cheaper models for Stage 1; implement usage quotas. |
| Users ask questions requiring JOINs or multi-table analysis | Medium | Medium | P2 feature: detect multi-table intent and attempt auto-JOIN with schema compatibility check. |
| Security: prompt injection via user questions | Medium | Low | Strict output validation; SQL whitelist (SELECT only); parameterized queries where possible. |

---

## 14. Open Questions

1. **Dataset Availability:** Do we have the 100+ CSVs now, or should the MVP use synthetic/sample data?
2. **Thematic Scope:** Are all CSVs Nigeria-focused sustainability data, or do we expect mixed topics?
3. **LLM Provider:** Will we use OpenAI GPT-4, Anthropic Claude, or a local open-source model? Is there a budget for API costs?
4. **Deployment:** Is this intended for local use, internal team use, or public web deployment?
5. **Multi-table JOINs:** Is cross-dataset analysis (e.g., "Compare CO2 and energy consumption by state") a P1 or P2 requirement?
6. **Authentication:** Do we need user accounts, or is it open access? Should CSV upload be admin-only?
7. **Language Support:** Should the UI and natural language understanding support Pidgin English or local Nigerian languages?

---

## 15. Appendix

### A. Glossary
- **Schema Document:** A human-readable text block describing a table's structure, generated for LLM consumption.
- **Schema Registry:** The central SQLite table storing metadata for all loaded CSVs.
- **Two-Stage Pipeline:** The architecture splitting query resolution into (1) table selection and (2) SQL generation.
- **Text-to-SQL:** The task of converting natural language questions into executable SQL queries.

### B. Reference Files
- Architecture diagram: See Section 6.1
- File structure: See original architecture document
- Sample schema doc: See Section 3 of original architecture document

### C. Dependencies
- Python 3.10+
- Streamlit
- Pandas
- SQLite3
- LLM SDK (openai / anthropic / litellm)
- Plotly or Altair (charts)

---

**End of Document**

*This PRD is a living document. Requirements may be refined as the project progresses through MVP, Alpha, Beta, and Launch phases.*
