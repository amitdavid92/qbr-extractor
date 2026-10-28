"""Review UI for processed QBR reports.

    streamlit run app/streamlit_app.py

A thin layer over the same pipeline and database the CLI uses; it adds no logic of its own.
"""

import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from qbr_extractor.extractor import Extractor
from qbr_extractor.llm import GeminiClient
from qbr_extractor.pdf_reader import read_pdf
from qbr_extractor.pipeline import Pipeline
from qbr_extractor.record import QbrRecord
from qbr_extractor.storage import Repository

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "output/qbr.db"
CACHE_DIR = ROOT / ".cache/llm"
UPLOAD_DIR = ROOT / "output/uploads"
PDF_DIRS = [ROOT / "data/input", ROOT / "data/holdout", UPLOAD_DIR]

load_dotenv(ROOT / ".env")
st.set_page_config(page_title="QBR Extractor", layout="wide")


def repo() -> Repository:
    # SQLite connections are per-thread; Streamlit reruns the script per interaction, so open one per run.
    return Repository(DB_PATH)


def load_documents() -> pd.DataFrame:
    r = repo()
    try:
        return pd.read_sql_query(
            """SELECT d.id, d.file_name, d.status, r.customer_name, r.period_label, r.period_year,
                      r.period_quarter, d.prompt_version,
                      (SELECT COUNT(*) FROM issues s WHERE s.document_id = d.id AND s.severity != 'info') AS flags,
                      d.error
               FROM documents d LEFT JOIN reports r ON r.document_id = d.id ORDER BY d.file_name""",
            r.conn,
        )
    finally:
        r.close()


def load_record(doc_id: int) -> tuple[str, str | None, QbrRecord | None]:
    r = repo()
    try:
        [(_, name, status, error, record_json)] = r.find_documents(str(doc_id))
    finally:
        r.close()
    return status, error, QbrRecord.model_validate_json(record_json) if record_json else None


def find_pdf(file_name: str) -> Path | None:
    return next((d / file_name for d in PDF_DIRS if (d / file_name).exists()), None)


def period_text(rec: QbrRecord) -> str:
    p = rec.period
    if p.quarter:
        return f"Q{p.quarter} {p.year or '????'}"
    return p.label or "-"


def mark(ok: bool) -> str:
    return "✅" if ok else "❌"


def with_raw(value, raw: str | None) -> str:
    """Normalized value, or '—' plus what the document actually said (e.g. '— (TBD)')."""
    if value:
        return str(value)
    return f"— ({raw})" if raw else "—"


# ------------------------------------------------------------------ pages


def overview_page() -> None:
    docs = load_documents()
    if docs.empty:
        st.info("No documents yet. Run `qbr process data/input` or upload a PDF.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Documents", len(docs))
    c2.metric("OK", int((docs.status == "success").sum()))
    c3.metric("Needs review", int((docs.status == "needs_review").sum()))
    c4.metric("Failed", int((docs.status == "failed").sum()))

    st.subheader("Documents")
    view = docs.assign(
        period=docs.apply(lambda d: f"Q{int(d.period_quarter)} {int(d.period_year) if pd.notna(d.period_year) else '????'}"
                          if pd.notna(d.period_quarter) else (d.period_label or "-"), axis=1),
        status=docs.status.map({"success": "✅ OK", "needs_review": "⚠️ Needs review", "failed": "❌ Failed"}),
    )[["id", "file_name", "status", "customer_name", "period", "flags", "prompt_version"]]
    st.dataframe(view, hide_index=True, width="stretch")

    st.subheader("Review queue")
    r = repo()
    try:
        queue = pd.read_sql_query(
            """SELECT r.customer_name AS customer, s.severity, s.field, s.reason
               FROM issues s JOIN documents d ON d.id = s.document_id LEFT JOIN reports r ON r.document_id = d.id
               WHERE s.severity != 'info' ORDER BY s.severity, d.file_name""",
            r.conn,
        )
    finally:
        r.close()
    if queue.empty:
        st.success("Nothing to review.")
    else:
        st.dataframe(queue, hide_index=True, width="stretch")


def report_page() -> None:
    docs = load_documents()
    if docs.empty:
        st.info("No documents yet.")
        return
    ids = {f"{row.customer_name or row.file_name}  ·  {row.file_name}": int(row.id) for row in docs.itertuples()}
    doc_id = ids[st.selectbox("Report", list(ids))]
    status, error, rec = load_record(doc_id)
    if rec is None:
        st.error(f"Processing failed: {error}")
        return

    left, right = st.columns([3, 2])
    with left:
        render_record(rec)
    with right:
        st.subheader("Source text (what the model saw)")
        pdf = find_pdf(rec.file_name)
        if pdf is None:
            st.caption("Original PDF not found locally.")
        else:
            with st.container(height=900):
                st.markdown(read_pdf(pdf).text)


def render_record(rec: QbrRecord) -> None:
    if rec.needs_review:
        st.warning("⚠️ Needs human review")
    else:
        st.success("✅ No blocking issues")

    c1, c2, c3 = st.columns(3)
    c1.metric("Customer", rec.customer.name or "-", rec.customer.status, delta_color="off")
    c2.metric("Period", period_text(rec), rec.period.status, delta_color="off")
    c3.metric("Report date", str(rec.report_date.value or "-"), rec.report_date.precision or "", delta_color="off")

    issues = sorted(rec.issues, key=lambda i: ("error", "warning", "info").index(i.severity))
    if issues:
        with st.expander(f"Issues ({len(issues)})", expanded=rec.needs_review):
            for i in issues:
                {"error": st.error, "warning": st.warning, "info": st.info}[i.severity](f"**{i.field}** — {i.reason}")

    st.markdown("**Executive summary** _(generated)_")
    st.write(rec.executive_summary)

    st.markdown("**KPIs**")
    st.dataframe(pd.DataFrame([{
        "": mark(k.values_verified), "metric": k.name, "as written": k.value_raw, "value": k.value_num,
        "unit": k.unit, "≈": "~" if k.is_approximate else "", "previous": k.previous_raw,
        "target": k.target_raw, "met": {True: "✅", False: "❌", None: ""}[k.target_met],
    } for k in rec.kpis]), hide_index=True, width="stretch")

    st.markdown("**Action items**")
    st.dataframe(pd.DataFrame([{
        "": mark(a.values_verified), "action": a.description,
        "owner": with_raw(a.owner, a.owner_raw),
        "due": with_raw(f"{a.due_date} ({a.due_date_precision})" if a.due_date else None, a.due_date_raw),
    } for a in rec.action_items]), hide_index=True, width="stretch")

    tabs = st.tabs(["Goals", "Achievements", "Challenges", "Risks", "Conflicts"])
    for tab, item_type in zip(tabs[:4], ["goal", "achievement", "challenge", "risk"]):
        with tab:
            items = [i for i in rec.items if i.item_type == item_type]
            if not items:
                st.caption("None found.")
                continue
            st.dataframe(pd.DataFrame([{
                "": mark(i.quote_verified), "item": i.description,
                "scope / status": " · ".join(x for x in (i.scope, i.status) if x), "source quote": i.source_quote,
            } for i in items]), hide_index=True, width="stretch")
    with tabs[4]:
        if not rec.conflicts:
            st.caption("No conflicts.")
        for c in rec.conflicts:
            st.warning(f"**{c.topic}**: {' vs '.join(c.values)}")
            for q in c.source_quotes:
                st.caption(f"“{q}”")

    st.caption(f"✅ = found in the document · ❌ = not found (possible hallucination) · "
               f"model {rec.model} · prompt {rec.prompt_version}")


def upload_page() -> None:
    st.write("Upload a QBR PDF to extract it with the same pipeline as the CLI.")
    uploaded = st.file_uploader("QBR report (PDF)", type="pdf")
    if uploaded is None:
        return
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        st.error("GEMINI_API_KEY is not set. Add it to .env.")
        return
    if not st.button("Process", type="primary"):
        return

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / Path(uploaded.name).name
    path.write_bytes(uploaded.getvalue())

    client = GeminiClient(api_key, os.environ.get("GEMINI_MODEL", "gemini-3.5-flash"))
    r = repo()
    try:
        with st.spinner("Extracting (about 20 seconds)..."):
            result = Pipeline(Extractor(client, CACHE_DIR), r).process_file(path)
    finally:
        r.close()

    if result.status == "failed":
        st.error(f"Processing failed: {result.error}")
    else:
        st.success(f"Done: {result.status}. Open the **Report** tab to review it.")
        render_record(result.record)


st.title("QBR Extractor")
overview, report, upload = st.tabs(["Overview", "Report", "Upload"])
with overview:
    overview_page()
with report:
    report_page()
with upload:
    upload_page()
