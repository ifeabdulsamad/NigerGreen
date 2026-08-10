# NaijaGreen Chat 🌍

Multi-schema text-to-SQL engine for sustainability datasets.
Upload CSVs → auto schema inference → ask questions in plain English →
LLM-generated, validated SQL → table + chart + plain-English summary.

## Quick start (no API key — demo mode)

```bash
pip install -r requirements.txt
export DEMO_MODE=true
streamlit run app.py          # → http://localhost:8501
```

Upload `data/emissions_lagos.csv` in the sidebar, then ask:

- "total co2 emissions per year"
- "average co2 emissions"
- "show me all data"

## With a DeepSeek API key (full LLM pipeline)

```bash
cp .env.example .env           # set DEEPSEEK_API_KEY=...
pip install -r requirements.txt
streamlit run app.py
```

Two-stage pipeline: `deepseek/deepseek-chat` selects the schema and writes
the SQL (fallback `deepseek/deepseek-reasoner`). All SQL is AST-validated
(single SELECT, whitelisted table, no DML/PRAGMA) and runs under a 5s
timeout.

## Docker

```bash
docker compose up --build      # app on :8501
```

## Tests

```bash
pytest -q                      # unit + mocked-LLM integration + property fuzz
```

See `docs/TRD.md` and `docs/ARCHITECTURE.md` for the full spec.
