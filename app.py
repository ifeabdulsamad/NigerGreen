"""NaijaGreen Chat — Streamlit UI (TRD §2.2 UI Layer).

Upload sustainability CSVs -> auto schema inference -> chat in natural
language -> two-stage LLM pipeline -> table + chart + SQL.

Two modes:
  Mode 1: "Upload Your Data" — upload any CSV, ask questions
  Mode 2: "Nigeria SDG Intelligence" — 181 preloaded Nigeria SDG datasets
"""

from __future__ import annotations

import utils.http_session
import utils.transport
import utils.session
import os
import time
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st

from config import Config, get_config
from logger import setup_logging
from database import DatabaseManager
from schema_registry import SchemaRegistry, CSVValidationError
from cache_manager import CacheManager
from sql_engine import TextToSQLEngine, EngineError

# ----------------------------------------------------------------------
st.set_page_config(
    page_title="NaijaGreen Chat",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ----------------------------------------------------------------------
# Modern startup UI — glass-morphism, Space Grotesk, gradient accents.
# ----------------------------------------------------------------------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&display=swap');

    /* ── Root ──────────────────────────────────────────────────── */
    .stApp {
        background: #080f0a;
        background-image:
            radial-gradient(ellipse at 50% 0%, rgba(46, 160, 67, 0.06) 0%, transparent 70%),
            radial-gradient(ellipse at 80% 100%, rgba(29, 209, 161, 0.04) 0%, transparent 60%);
    }
    .stMainBlockContainer, .block-container { background: transparent; }

    /* ── Typography ────────────────────────────────────────────── */
    html, body, [class*="css"] {
        font-family: 'Space Grotesk', 'Segoe UI', system-ui, -apple-system, sans-serif;
        color: #e8f5ec;
        letter-spacing: -0.01em;
    }
    h1, h2, h3, h4 { font-family: 'Space Grotesk', sans-serif; color: #e8f5ec; font-weight: 700; }
    p, span, div { color: #e8f5ec; }
    .stCaption { color: #7a9e85 !important; font-size: 0.85rem; }

    /* ── Glass panel utility ───────────────────────────────────── */
    .glass-panel {
        background: rgba(12, 28, 18, 0.5);
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        border: 1px solid rgba(46, 160, 67, 0.12);
        border-radius: 16px;
    }

    /* ── Sidebar ───────────────────────────────────────────────── */
    [data-testid="stSidebar"] {
        background: rgba(6, 16, 10, 0.85);
        backdrop-filter: blur(24px);
        -webkit-backdrop-filter: blur(24px);
        border-right: 1px solid rgba(46, 160, 67, 0.1);
    }
    [data-testid="stSidebar"] * { color: #e8f5ec; }
    [data-testid="stSidebar"] .stCaption { color: #7a9e85 !important; }
    [data-testid="stSidebar"] input, [data-testid="stSidebar"] textarea {
        background: rgba(12, 28, 18, 0.4) !important;
        color: #e8f5ec !important;
        border: 1px solid rgba(46, 160, 67, 0.15) !important;
        border-radius: 10px !important;
    }
    [data-testid="stSidebar"] button {
        background: rgba(12, 28, 18, 0.5) !important;
        color: #e8f5ec !important;
        border: 1px solid rgba(46, 160, 67, 0.15) !important;
        border-radius: 10px !important;
        font-family: 'Space Grotesk', sans-serif !important;
        transition: all 0.25s ease !important;
    }
    [data-testid="stSidebar"] button:hover {
        background: rgba(46, 160, 67, 0.2) !important;
        border-color: rgba(46, 160, 67, 0.4) !important;
    }

    /* ── Mode cards ─────────────────────────────────────────────── */
    .ng-mode-card {
        background: rgba(12, 28, 18, 0.45);
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        border: 1px solid rgba(46, 160, 67, 0.12);
        border-radius: 20px;
        padding: 2.2rem 2rem;
        transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
        height: 100%;
        position: relative;
        overflow: hidden;
    }
    .ng-mode-card::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 1px;
        background: linear-gradient(90deg, transparent, rgba(46, 160, 67, 0.3), transparent);
        opacity: 0;
        transition: opacity 0.35s ease;
    }
    .ng-mode-card:hover {
        border-color: rgba(46, 160, 67, 0.35);
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3), 0 0 0 1px rgba(46, 160, 67, 0.08);
        transform: translateY(-3px);
    }
    .ng-mode-card:hover::before { opacity: 1; }
    .ng-mode-card .ng-card-icon {
        font-size: 2.8rem;
        margin-bottom: 0.8rem;
    }
    .ng-mode-card .ng-card-title {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 1.35rem;
        color: #e8f5ec;
        font-weight: 700;
        margin-bottom: 0.5rem;
        letter-spacing: -0.02em;
    }
    .ng-mode-card .ng-card-desc {
        color: #7a9e85;
        font-size: 0.93rem;
        line-height: 1.6;
    }

    /* ── Metrics ────────────────────────────────────────────────── */
    [data-testid="stMetric"] {
        background: rgba(12, 28, 18, 0.4);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        border: 1px solid rgba(46, 160, 67, 0.1);
        border-radius: 14px;
        padding: 0.8rem 1rem;
        transition: all 0.25s ease;
    }
    [data-testid="stMetric"]:hover {
        border-color: rgba(46, 160, 67, 0.25);
        transform: translateY(-1px);
    }
    [data-testid="stMetricLabel"] { color: #7a9e85 !important; font-family: 'Space Grotesk', sans-serif; }
    [data-testid="stMetricValue"] { color: #e8f5ec !important; font-family: 'Space Grotesk', sans-serif; font-weight: 700; }

    /* ── Chat bubbles ──────────────────────────────────────────── */
    [data-testid="stChatMessage"] {
        border-radius: 18px;
        padding: 0.7rem 1rem;
        margin-bottom: 0.4rem;
    }
    [data-testid="stChatMessage"]:has(div[data-testid="chatAvatarIcon-user"]) {
        background: rgba(18, 38, 28, 0.5);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        border: 1px solid rgba(46, 160, 67, 0.08);
    }
    [data-testid="stChatMessage"]:has(div[data-testid="chatAvatarIcon-assistant"]) {
        background: rgba(8, 24, 14, 0.55);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        border: 1px solid rgba(46, 160, 67, 0.15);
    }

    /* ── Buttons ────────────────────────────────────────────────── */
    .stButton > button {
        font-family: 'Space Grotesk', sans-serif !important;
        font-weight: 600 !important;
        background: rgba(12, 28, 18, 0.5) !important;
        color: #e8f5ec !important;
        border: 1px solid rgba(46, 160, 67, 0.2) !important;
        border-radius: 10px !important;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
    }
    .stButton > button:hover {
        background: rgba(46, 160, 67, 0.2) !important;
        border-color: rgba(46, 160, 67, 0.4) !important;
        transform: translateY(-1px);
    }
    /* Primary CTA: gradient */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #2ea043, #1dd1a1) !important;
        color: #ffffff !important;
        border: none !important;
        font-weight: 700 !important;
        box-shadow: 0 4px 16px rgba(46, 160, 67, 0.25);
    }
    .stButton > button[kind="primary"]:hover {
        background: linear-gradient(135deg, #3fb950, #2ee4b0) !important;
        box-shadow: 0 6px 24px rgba(46, 160, 67, 0.35);
        transform: translateY(-2px);
    }

    /* ── Example chips ──────────────────────────────────────────── */
    div[data-testid="stHorizontalBlock"] div[data-testid="stButton"] button {
        font-family: 'Space Grotesk', sans-serif !important;
        border-radius: 999px !important;
        border: 1px solid rgba(46, 160, 67, 0.2) !important;
        background: rgba(12, 28, 18, 0.4) !important;
        color: #7a9e85 !important;
        font-weight: 500 !important;
        transition: all 0.25s ease !important;
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
    }
    div[data-testid="stHorizontalBlock"] div[data-testid="stButton"] button:hover {
        background: linear-gradient(135deg, #2ea043, #1dd1a1) !important;
        color: #ffffff !important;
        border-color: transparent !important;
        transform: translateY(-2px);
        box-shadow: 0 4px 16px rgba(46, 160, 67, 0.25);
    }

    /* ── Summary card ───────────────────────────────────────────── */
    .ng-summary {
        background: rgba(12, 28, 18, 0.45);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        border-left: 3px solid;
        border-image: linear-gradient(180deg, #2ea043, #1dd1a1) 1;
        border-radius: 12px;
        padding: 0.9rem 1.2rem;
        margin: 0.4rem 0 1rem 0;
        font-size: 1.04rem;
        color: #e8f5ec;
        line-height: 1.5;
    }
    @supports not (border-image: linear-gradient(180deg, #2ea043, #1dd1a1) 1) {
        .ng-summary { border-left: 3px solid #2ea043; }
    }

    /* ── Expanders ──────────────────────────────────────────────── */
    [data-testid="stExpander"] {
        background: rgba(12, 28, 18, 0.35);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid rgba(46, 160, 67, 0.1);
        border-radius: 12px;
    }
    [data-testid="stExpander"] * { color: #e8f5ec; }

    /* ── Inputs ─────────────────────────────────────────────────── */
    .stTextInput > div > div > input, textarea, .stFileUploader > div > div {
        font-family: 'Space Grotesk', sans-serif !important;
        background: rgba(12, 28, 18, 0.4) !important;
        color: #e8f5ec !important;
        border: 1px solid rgba(46, 160, 67, 0.15) !important;
        border-radius: 10px !important;
    }
    textarea { background: rgba(12, 28, 18, 0.4) !important; color: #e8f5ec !important; }

    /* ── Chat input area ────────────────────────────────────────── */
    [data-testid="stChatInput"] textarea {
        background: rgba(12, 28, 18, 0.5) !important;
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        border: 1px solid rgba(46, 160, 67, 0.2) !important;
        border-radius: 14px !important;
    }

    /* ── Dividers ───────────────────────────────────────────────── */
    hr, [data-testid="stDivider"] { border-color: rgba(46, 160, 67, 0.1); }

    /* ── Segmented control ──────────────────────────────────────── */
    [data-testid="stSegmentedControl"] {
        background: rgba(12, 28, 18, 0.4);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid rgba(46, 160, 67, 0.12);
        border-radius: 10px;
    }

    /* ── Code blocks ────────────────────────────────────────────── */
    .stCodeBlock, .stCodeBlock * { color: #c8f0d4 !important; }
    .stCodeBlock {
        background: rgba(8, 20, 12, 0.6) !important;
        border: 1px solid rgba(46, 160, 67, 0.12);
        border-radius: 12px;
    }

    /* ── Info / warning / error ─────────────────────────────────── */
    [data-testid="stInfo"] {
        background: rgba(12, 28, 18, 0.4);
        border: 1px solid rgba(46, 160, 67, 0.15);
        border-radius: 12px;
    }
    [data-testid="stError"] { color: #f85149; }

    /* ── Dataframe / table ──────────────────────────────────────── */
    [data-testid="stDataFrame"] {
        border-radius: 12px;
        overflow: hidden;
    }

    /* ── Spinner ────────────────────────────────────────────────── */
    [data-testid="stSpinner"] { color: #2ea043; }

    /* ── File uploader dropzone ─────────────────────────────────── */
    [data-testid="stFileUploader"] section {
        background: rgba(12, 28, 18, 0.3) !important;
        border: 2px dashed rgba(46, 160, 67, 0.2) !important;
        border-radius: 14px !important;
        transition: all 0.25s ease !important;
    }
    [data-testid="stFileUploader"] section:hover {
        border-color: rgba(46, 160, 67, 0.5) !important;
        background: rgba(12, 28, 18, 0.5) !important;
    }

    /* ── Subtle bg orbs (landing hero) ──────────────────────────── */
    .ng-hero-orb {
        position: fixed;
        border-radius: 50%;
        filter: blur(120px);
        pointer-events: none;
        z-index: 0;
    }
    .ng-hero-orb--top {
        width: 600px; height: 600px;
        background: rgba(46, 160, 67, 0.06);
        top: -200px; left: 50%; transform: translateX(-50%);
    }
    .ng-hero-orb--bottom {
        width: 400px; height: 400px;
        background: rgba(29, 209, 161, 0.05);
        bottom: -100px; right: -100px;
    }
    </style>

    <div class="ng-hero-orb ng-hero-orb--top"></div>
    <div class="ng-hero-orb ng-hero-orb--bottom"></div>
    """,
    unsafe_allow_html=True,
)


# ----------------------------------------------------------------------
# Backend (cached once per process)
# ----------------------------------------------------------------------
@st.cache_resource
def init_backend() -> dict:
    """Build the shared backend once per process (not per rerun)."""
    cfg = get_config()
    setup_logging(cfg.log_level, json=cfg.log_json)
    db = DatabaseManager(cfg.db_path, wal_mode=True, timeout_ms=cfg.query_timeout_ms)
    cache = CacheManager(
        enabled=cfg.cache_enabled,
        schema_ttl_s=cfg.cache_schema_ttl_s,
        sql_ttl_s=cfg.cache_sql_ttl_s,
        result_ttl_s=cfg.cache_result_ttl_s,
        max_entries=cfg.cache_max_entries,
    )
    registry = SchemaRegistry(db, data_dir=str(cfg.resolved_data_dir))
    engine = TextToSQLEngine(cfg, registry, cache)
    return {
        "config": cfg,
        "db": db,
        "cache": cache,
        "registry": registry,
        "engine": engine,
    }


# ----------------------------------------------------------------------
# SDG data preloader (cached once per process)
# ----------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def preload_sdg_data(_registry, sdg_dir: str) -> dict:
    """Load all Nigeria SDG CSVs into the registry. Cached once per process.

    Returns a dict with keys: count, total, errors, load_time_s.
    Files that fail validation are recorded in ``errors`` but don't stop
    the batch.
    """
    sdg_path = Path(sdg_dir)
    csv_files = sorted(sdg_path.glob("*.csv"))
    total = len(csv_files)
    loaded = 0
    errors: list[dict] = []
    t0 = time.perf_counter()

    if total == 0:
        return {"count": 0, "total": 0, "errors": [], "load_time_s": 0.0}

    status = st.status(f"Loading {total} Nigeria SDG datasets…", expanded=True)
    progress_bar = st.progress(0, text="Starting…")

    for i, csv_file in enumerate(csv_files):
        try:
            sdg_num = csv_file.stem.split("-")[0]
            tag = f"sdg{sdg_num}"
            _registry.register_csv(str(csv_file), thematic_tags=[tag, "nigeria", "sdg"])
            loaded += 1
        except Exception as exc:
            errors.append({"file": csv_file.name, "error": str(exc)})

        progress_bar.progress(
            (i + 1) / total,
            text=f"{i + 1}/{total}: {csv_file.name}",
        )

    elapsed = time.perf_counter() - t0
    progress_bar.progress(1.0, text=f"Done — {loaded}/{total} loaded in {elapsed:.1f}s")
    status.update(label=f"Loaded {loaded} Nigeria SDG datasets", state="complete")

    return {
        "count": loaded,
        "total": total,
        "errors": errors,
        "load_time_s": round(elapsed, 1),
    }


# ----------------------------------------------------------------------
# Instantiate backend
# ----------------------------------------------------------------------
backend = init_backend()
cfg: Config = backend["config"]
registry: SchemaRegistry = backend["registry"]
engine: TextToSQLEngine = backend["engine"]
engine.demo_mode = False


# ----------------------------------------------------------------------
# Result rendering helpers
# ----------------------------------------------------------------------
def _render_chart(df: pd.DataFrame, chart_type: str = "bar") -> None:
    """Render a Plotly chart; plotly is imported lazily so that app startup
    (and every rerun without a chart) never pays its ~10s import cost.
    Best-effort: missing/invalid plotly degrades to no chart."""
    try:
        import plotly.express as px
    except ImportError:  # pragma: no cover - env without plotly
        return
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    if not numeric_cols:
        return
    x = df.columns[0]
    y = numeric_cols[-1]
    try:
        if chart_type == "pie":
            fig = px.pie(
                df, names=x, values=y, title=f"{y} by {x}", template="plotly_dark"
            )
        elif chart_type == "line":
            fig = px.line(
                df, x=x, y=y, title=f"{y} by {x}", markers=True, template="plotly_dark"
            )
        else:
            fig = px.bar(df, x=x, y=y, title=f"{y} by {x}", template="plotly_dark")
        st.plotly_chart(fig, width="stretch")
    except Exception:  # noqa: BLE001 - charting is best-effort
        return


def render_result(detail: dict, chart_type: str, dl_key: str = "dl") -> None:
    """Render one assistant answer: timing, summary card, chart, table,
    CSV download and the generated SQL (shared by history + live reply)."""
    if detail.get("error"):
        st.error(detail["error"])
        return
    st.caption(
        f"⏱ {detail.get('execution_time_ms', 0):.0f} ms · "
        f"cached: {detail.get('cached', False)}"
    )
    if detail.get("nl_summary"):
        st.markdown(
            f'<div class="ng-summary">{detail["nl_summary"]}</div>',
            unsafe_allow_html=True,
        )
    df = detail.get("results")
    if isinstance(df, pd.DataFrame) and not df.empty:
        _render_chart(df, chart_type)
        st.dataframe(df, width="stretch")
        st.download_button(
            "⬇ Download CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="naijagreen_result.csv",
            mime="text/csv",
            key=dl_key,
        )
    if detail.get("sql"):
        with st.expander("Generated SQL"):
            st.code(detail["sql"], language="sql")
    st.caption("Was this helpful? 👍 👎 (stored locally)")


def process_question(question: str, chart_type: str) -> None:
    """Ask a question: append the user message, run the engine, render the
    assistant answer inline and append it to the session history."""
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user", avatar="🧑🏾‍💻"):
        st.markdown(question)

    with st.chat_message("assistant", avatar="🌍"):
        with st.spinner("Thinking…"):
            result = engine.answer_question(question)
        render_result(result, chart_type, dl_key="dl_live")

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": result.get("nl_summary") or result.get("error") or "",
            "detail": result,
        }
    )


# ----------------------------------------------------------------------
# Shared sidebar: LLM settings
# ----------------------------------------------------------------------
def _render_sidebar_llm() -> None:
    """LLM status block shown at the top of the sidebar in every mode."""
    st.sidebar.subheader("LLM settings")
    key_status = (
        "✅ API connected" if cfg.deepseek_api_key else "⚠️ No API key configured"
    )
    st.sidebar.caption(f"{key_status} · schema: {cfg.schema_model}")
    st.sidebar.caption(f"sql: {cfg.sql_model}")


# ----------------------------------------------------------------------
# Sidebar: Upload mode
# ----------------------------------------------------------------------
def _render_sidebar_upload() -> None:
    """Sidebar content for Mode 1 (Upload Your Data)."""
    st.sidebar.title("NaijaGreen Chat")
    st.sidebar.caption("Upload your own CSV & query with natural language")

    # ── Back to home ────────────────────────────────────────────
    if st.sidebar.button("← Back to home", key="btn_home_upload"):
        st.session_state.page_mode = "landing"
        st.session_state.messages = []
        st.rerun()
    st.sidebar.divider()

    _render_sidebar_llm()
    st.sidebar.divider()

    # ── File uploader ────────────────────────────────────────────
    st.sidebar.subheader("Upload CSV")
    uploaded = st.sidebar.file_uploader(
        "Choose a CSV file",
        type=["csv"],
        accept_multiple_files=False,
        help="Max 20MB. Header row required.",
    )
    if uploaded is not None:
        tmp = cfg.resolved_upload_dir / uploaded.name
        tmp.write_bytes(uploaded.getbuffer())
        try:
            table_id = registry.register_csv(str(tmp))
            st.sidebar.success(f"Registered {uploaded.name} as {table_id}")
            st.cache_data.clear()
            st.rerun()
        except CSVValidationError as exc:
            st.sidebar.error(f"Rejected: {exc}")
        except Exception as exc:  # noqa: BLE001
            st.sidebar.error(f"Registration failed: {exc}")

    # ── Dataset browser ──────────────────────────────────────────
    _render_dataset_browser()

    # ── Cache stats ──────────────────────────────────────────────
    if st.sidebar.button("Cache stats"):
        st.sidebar.json(backend["cache"].stats())


# ----------------------------------------------------------------------
# Sidebar: SDG mode
# ----------------------------------------------------------------------
def _render_sidebar_sdg() -> None:
    """Sidebar content for Mode 2 (Nigeria SDG Intelligence)."""
    st.sidebar.title("NaijaGreen Chat")
    st.sidebar.caption("Nigeria SDG Intelligence · 181 datasets preloaded")

    # ── Back to home ────────────────────────────────────────────
    if st.sidebar.button("← Back to home", key="btn_home_sdg"):
        st.session_state.page_mode = "landing"
        st.session_state.messages = []
        st.rerun()
    st.sidebar.divider()

    _render_sidebar_llm()
    st.sidebar.divider()

    # ── Load summary ────────────────────────────────────────────
    summary = st.session_state.get("sdg_load_summary", {})
    if summary:
        loaded = summary.get("count", 0)
        total = summary.get("total", 0)
        t = summary.get("load_time_s", 0)
        st.sidebar.caption(f"📊 {loaded}/{total} datasets loaded in {t:.1f}s")
        errs = summary.get("errors", [])
        if errs:
            with st.sidebar.expander(f"{len(errs)} file(s) skipped"):
                for e in errs:
                    st.sidebar.caption(f"• {e['file']}: {e['error']}")

    # ── Dataset browser ──────────────────────────────────────────
    _render_dataset_browser()

    # ── Cache stats ──────────────────────────────────────────────
    if st.sidebar.button("Cache stats"):
        st.sidebar.json(backend["cache"].stats())


# ----------------------------------------------------------------------
# Shared dataset browser (used in both upload and SDG sidebars)
# ----------------------------------------------------------------------
def _render_dataset_browser() -> None:
    """Topic filter + search + scrollable dataset list with delete buttons."""
    schemas = registry.get_all_schemas()
    metas = {m["table_id"]: m for m in registry.get_metas()}
    st.sidebar.caption(f"{len(schemas)} table(s) registered")

    # Topic filter
    topic_counts = Counter(
        (tags[0] if tags else "other") for *_s, tags in schemas if tags
    )
    top_topics = [t for t, _c in topic_counts.most_common(6)]
    topic_opts = ["All"] + top_topics
    topic = st.sidebar.segmented_control(
        "Topic",
        options=topic_opts,
        default="All",
        key="topic",
        help="Narrow the dataset list by theme.",
    )
    topic_schemas = schemas if topic == "All" else [s for s in schemas if topic in s[3]]

    # Search
    shown = st.sidebar.text_input(
        "Filter datasets",
        placeholder="e.g. sdg7",
        help="Type to narrow the list below.",
    )
    needle = shown.strip().lower()
    filtered = (
        [s for s in topic_schemas if needle in s[1].lower()]
        if needle
        else topic_schemas
    )

    MAX_SIDEBAR_TABLES = 8
    visible = filtered[:MAX_SIDEBAR_TABLES]
    if len(filtered) > MAX_SIDEBAR_TABLES:
        st.sidebar.caption(
            f"Showing {MAX_SIDEBAR_TABLES} of {len(filtered)} — use the filter above."
        )
    for tid, tname, doc, _tags in visible:
        meta = metas.get(tid)
        ver = meta["version"] if meta else 1
        rc = (
            f" · {meta['row_count']:,} rows × {meta['column_count']} cols"
            if meta
            else ""
        )
        with st.sidebar.expander(f"{tname} (v{ver}){rc}"):
            st.code(doc.splitlines()[0] if doc else "", language=None)
            if st.button("🗑 delete", key=f"del_{tid}"):
                registry.delete_schema(tid)
                st.cache_data.clear()
                st.rerun()


# ----------------------------------------------------------------------
# Chart type selector (shared across modes that show chat)
# ----------------------------------------------------------------------
def _render_chart_selector() -> str:
    """Return the currently selected chart type."""
    return (
        st.sidebar.segmented_control(
            "Chart type",
            options=["bar", "line", "pie"],
            default="bar",
            key="chart_type",
            help="Chart style used for query results.",
        )
        or "bar"
    )


# ----------------------------------------------------------------------
# Shared chat area (history + input + example chips)
# ----------------------------------------------------------------------
def _render_chat_area(examples: list[str], welcome_subtitle: str) -> None:
    """Render chat history, welcome / example chips, and the chat input.

    Parameters
    ----------
    examples : list[str]
        Example questions shown as clickable chips (3 per row) on the
        welcome screen before any messages are sent.
    welcome_subtitle : str
        A one-line description shown above the example chips.
    """
    if not st.session_state.messages:
        st.markdown(
            f"""
            <div style="text-align:center;padding:2rem 0 0.5rem 0;position:relative;z-index:1;">
                <p style="font-family:'Space Grotesk',sans-serif;font-size:1.6rem;
                          font-weight:700;margin-bottom:0.3rem;letter-spacing:-0.02em;
                          background:linear-gradient(135deg,#3fb950,#1dd1a1);
                          -webkit-background-clip:text;-webkit-text-fill-color:transparent;
                          background-clip:text;">🌍 NaijaGreen Chat</p>
                <p style="font-family:'Space Grotesk',sans-serif;color:#7a9e85;
                          font-size:0.95rem;">{welcome_subtitle}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if examples:
            st.markdown("**Try one of these:**")
            ex_cols = st.columns(min(3, len(examples)))
            for i, ex in enumerate(examples):
                with ex_cols[i % 3]:
                    if st.button(ex, key=f"ex_{i}", use_container_width=True):
                        st.session_state.pending_question = ex
                        st.rerun()

    # Chat history
    chart_type = st.session_state.get("chart_type", "bar")
    for idx, msg in enumerate(st.session_state.messages):
        avatar = "🌍" if msg["role"] == "assistant" else "🧑🏾‍💻"
        with st.chat_message(msg["role"], avatar=avatar):
            if msg["role"] == "user":
                st.markdown(msg["content"])
            elif msg.get("detail"):
                render_result(msg["detail"], chart_type, dl_key=f"dl_{idx}")
            else:  # legacy assistant messages without detail
                st.markdown(msg["content"])

    # Chat input
    question = st.chat_input("Ask a question about your datasets…")
    pending = st.session_state.pop("pending_question", None)
    if question or pending:
        process_question(question or pending, chart_type)
        st.rerun()


# ----------------------------------------------------------------------
# Landing page renderer
# ----------------------------------------------------------------------
def _render_landing_page() -> None:
    """Landing page: gradient hero + glass mode cards + key stats."""
    # ── Hero ────────────────────────────────────────────────────
    st.markdown(
        """
        <div style="text-align:center;padding:3rem 0 2rem 0;position:relative;z-index:1;">
            <h1 style="font-family:'Space Grotesk',sans-serif;font-size:3.2rem;
                       font-weight:700;margin-bottom:0.6rem;letter-spacing:-0.03em;
                       background:linear-gradient(135deg,#3fb950 0%,#1dd1a1 100%);
                       -webkit-background-clip:text;-webkit-text-fill-color:transparent;
                       background-clip:text;">
                NaijaGreen Chat
            </h1>
            <p style="font-family:'Space Grotesk',sans-serif;color:#7a9e85;
                      font-size:1.15rem;max-width:580px;margin:0 auto 0.3rem auto;
                      line-height:1.5;">
                Ask questions about sustainability data in plain English.
                Pick a mode below to get started.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Mode cards ──────────────────────────────────────────────
    col1, col2 = st.columns(2, gap="large")

    with col1:
        st.markdown(
            """
            <div class="ng-mode-card">
                <div class="ng-card-icon">📁</div>
                <div class="ng-card-title">Upload Your Data</div>
                <div class="ng-card-desc">
                    Upload your own CSV datasets and query them with natural
                    language. Supports any sustainability data format
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button(
            "Upload Your Data →",
            key="btn_upload_mode",
            use_container_width=True,
            type="primary",
        ):
            st.session_state.page_mode = "upload"
            st.session_state.messages = []
            st.rerun()

    with col2:
        st.markdown(
            """
            <div class="ng-mode-card">
                <div class="ng-card-icon">🇳🇬</div>
                <div class="ng-card-title">Nigeria SDG Intelligence</div>
                <div class="ng-card-desc">
                    181 pre-loaded Nigeria SDG datasets covering all 17 UN
                    Sustainable Development Goals. No upload needed — just ask
                    about energy, health, education, poverty, and more.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button(
            "Explore SDG Data →",
            key="btn_sdg_mode",
            use_container_width=True,
            type="primary",
        ):
            st.session_state.page_mode = "sdg"
            st.session_state.messages = []
            st.rerun()

    # ── Key metrics ─────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    schemas = registry.get_all_schemas()
    metas = {m["table_id"]: m for m in registry.get_metas()}
    total_rows = sum((m["row_count"] for m in metas.values()), 0)
    topic_counts = Counter(
        (tags[0] if tags else "other") for *_s, tags in schemas if tags
    )
    top_topics = [t for t, _c in topic_counts.most_common(6)]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Registered datasets", f"{len(schemas):,}")
    m2.metric("Total rows", f"{total_rows:,}")
    m3.metric("Topics", f"{len(top_topics)}")
    m4.metric("Engine", "DeepSeek LLM")

    if top_topics:
        st.caption("**Covered topics:** " + " · ".join(top_topics))


# ----------------------------------------------------------------------
# Mode renderers
# ----------------------------------------------------------------------
UPLOAD_EXAMPLES = [
    "total co2 emissions per year",
    "average co2 emissions",
    "show me all data",
    "which state has the highest renewable share",
    "average ph by site",
]

SDG_EXAMPLES = [
    "Which state has the lowest electricity access in 2021?",
    "What is safe drinking water access in Lagos in 2020?",
    "Compare poverty rates between urban and rural areas",
    "Show me climate disaster trends over years",
    "Which geopolitical zone has the highest skilled birth attendance?",
]


def _render_upload_mode() -> None:
    """Mode 1: upload your own CSV and ask questions."""
    _render_sidebar_upload()
    chart_type = _render_chart_selector()

    schemas = registry.get_all_schemas()
    if not schemas:
        st.info("📁 Upload a CSV file in the sidebar to get started.")
        st.markdown(
            "Supported: any CSV with a header row, up to 20 MB. "
            "Once uploaded, you can ask questions in plain English."
        )
        # Still render the bottom expander
        st.divider()
        with st.expander("Registered datasets"):
            st.info("No datasets yet — upload a CSV in the sidebar.")
        return

    _render_chat_area(
        UPLOAD_EXAMPLES,
        "Upload a CSV in the sidebar and ask questions in plain English.",
    )

    # Bottom expander
    st.divider()
    with st.expander("Registered datasets"):
        schemas_all = registry.get_all_schemas()
        metas = {m["table_id"]: m for m in registry.get_metas()}
        if schemas_all:
            rows = []
            for tid, tname, _doc, tags in schemas_all:
                meta = metas.get(tid)
                rows.append(
                    {
                        "table_id": tid,
                        "table_name": tname,
                        "rows": meta["row_count"] if meta else 0,
                        "cols": meta["column_count"] if meta else 0,
                        "version": meta["version"] if meta else 0,
                        "tags": ", ".join(tags),
                    }
                )
            st.dataframe(pd.DataFrame(rows), width="stretch")
        else:
            st.info("No datasets yet — upload a CSV in the sidebar.")


def _render_sdg_mode() -> None:
    """Mode 2: Nigeria SDG Intelligence with 181 preloaded datasets."""
    _render_sidebar_sdg()
    chart_type = _render_chart_selector()

    # Preload SDG data (cached — instant on subsequent runs)
    sdg_dir = str(cfg.resolved_data_dir / "Nigeria-SDG-Data")
    if not Path(sdg_dir).exists():
        st.error(
            "Nigeria SDG data folder not found. "
            "Please ensure `data/Nigeria-SDG-Data/` exists with CSV files."
        )
        if st.button("← Back to home"):
            st.session_state.page_mode = "landing"
            st.rerun()
        return

    csv_count = len(list(Path(sdg_dir).glob("*.csv")))
    if csv_count == 0:
        st.error(f"No CSV files found in {sdg_dir}.")
        if st.button("← Back to home"):
            st.session_state.page_mode = "landing"
            st.rerun()
        return

    sdg_result = preload_sdg_data(registry, sdg_dir)
    st.session_state.sdg_load_summary = sdg_result

    loaded = sdg_result["count"]
    total = sdg_result["total"]
    t = sdg_result["load_time_s"]

    # Dispatch: if nothing loaded at all, show error
    if loaded == 0:
        st.error(f"Failed to load any of the {total} SDG datasets.")
        errs = sdg_result.get("errors", [])
        if errs:
            with st.expander("Details"):
                for e in errs[:20]:
                    st.caption(f"• {e['file']}: {e['error']}")
        return

    _render_chat_area(
        SDG_EXAMPLES,
        f"{loaded} Nigeria SDG datasets ready. "
        "Ask about energy, health, education, poverty, and more.",
    )

    # Bottom expander
    st.divider()
    with st.expander("Registered datasets"):
        schemas = registry.get_all_schemas()
        metas = {m["table_id"]: m for m in registry.get_metas()}
        if schemas:
            rows = []
            for tid, tname, _doc, tags in schemas:
                meta = metas.get(tid)
                rows.append(
                    {
                        "table_id": tid,
                        "table_name": tname,
                        "rows": meta["row_count"] if meta else 0,
                        "cols": meta["column_count"] if meta else 0,
                        "version": meta["version"] if meta else 0,
                        "tags": ", ".join(tags),
                    }
                )
            st.dataframe(pd.DataFrame(rows), width="stretch")
        else:
            st.info("No datasets registered.")


# ======================================================================
# Main routing
# ======================================================================
if "messages" not in st.session_state:
    st.session_state.messages = []

page_mode = st.session_state.get("page_mode", "landing")

if page_mode == "landing":
    _render_sidebar_llm()
    st.sidebar.divider()
    # Landing sidebar: minimal — just LLM status + key metrics
    schemas_landing = registry.get_all_schemas()
    st.sidebar.caption(f"{len(schemas_landing)} table(s) registered")
    _render_landing_page()

elif page_mode == "upload":
    _render_upload_mode()

elif page_mode == "sdg":
    _render_sdg_mode()
