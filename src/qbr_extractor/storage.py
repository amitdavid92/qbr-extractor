"""SQLite persistence. One row per document plus normalized child tables, so results
can be queried across customers and quarters with plain SQL.

Saving is idempotent per file hash: re-processing the same PDF replaces its rows.
"""

import sqlite3
from pathlib import Path

import pandas as pd

from .record import QbrRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id              INTEGER PRIMARY KEY,
    file_name       TEXT NOT NULL,
    file_hash       TEXT NOT NULL UNIQUE,
    status          TEXT NOT NULL CHECK (status IN ('success', 'needs_review', 'failed')),
    error           TEXT,
    model           TEXT,
    prompt_version  TEXT,
    processed_at    TEXT NOT NULL,
    record_json     TEXT              -- full normalized record, for audit / re-processing
);

CREATE TABLE IF NOT EXISTS reports (
    document_id           INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    customer_name         TEXT,
    customer_status       TEXT,
    period_label          TEXT,
    period_year           INTEGER,
    period_quarter        INTEGER,
    period_start          TEXT,
    period_end            TEXT,
    period_status         TEXT,
    report_date           TEXT,
    report_date_precision TEXT,
    executive_summary     TEXT
);

CREATE TABLE IF NOT EXISTS report_items (
    id             INTEGER PRIMARY KEY,
    document_id    INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    item_type      TEXT NOT NULL CHECK (item_type IN ('goal', 'achievement', 'challenge', 'risk')),
    description    TEXT NOT NULL,
    scope          TEXT,
    status         TEXT NOT NULL,
    source_quote   TEXT,
    quote_verified INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS kpis (
    id              INTEGER PRIMARY KEY,
    document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    value_raw       TEXT,
    value_num       REAL,
    unit            TEXT,
    is_approximate  INTEGER NOT NULL,
    comparator      TEXT,
    previous_raw    TEXT,
    previous_num    REAL,
    target_raw      TEXT,
    target_num      REAL,
    target_comparator TEXT,
    target_met      INTEGER,          -- NULL when the target has no explicit direction
    source_quote    TEXT,
    quote_verified  INTEGER NOT NULL,
    values_verified INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS action_items (
    id                 INTEGER PRIMARY KEY,
    document_id        INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    description        TEXT NOT NULL,
    owner              TEXT,
    owner_raw          TEXT,
    due_date           TEXT,
    due_date_precision TEXT,
    due_date_raw       TEXT,
    source_quote       TEXT,
    quote_verified     INTEGER NOT NULL,
    values_verified    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS issues (
    id          INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    field       TEXT NOT NULL,
    severity    TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'error')),
    reason      TEXT NOT NULL
);
"""

# Flat views used for the Excel export; joined to the customer so each sheet stands alone.
EXPORT_QUERIES = {
    "documents": """
        SELECT d.id, d.file_name, d.status, d.error, r.customer_name, r.period_label, r.period_year,
               r.period_quarter, r.period_status, r.report_date, r.executive_summary,
               d.model, d.prompt_version, d.processed_at
        FROM documents d LEFT JOIN reports r ON r.document_id = d.id ORDER BY d.file_name""",
    "items": """
        SELECT r.customer_name, i.item_type, i.scope, i.status, i.description, i.source_quote, i.quote_verified
        FROM report_items i JOIN reports r USING (document_id) ORDER BY r.customer_name, i.item_type""",
    "kpis": """
        SELECT r.customer_name, k.name, k.value_raw, k.value_num, k.unit, k.is_approximate, k.comparator,
               k.previous_raw, k.previous_num, k.target_raw, k.target_num, k.target_met, k.values_verified
        FROM kpis k JOIN reports r USING (document_id) ORDER BY r.customer_name, k.id""",
    "action_items": """
        SELECT r.customer_name, a.description, a.owner, a.owner_raw, a.due_date, a.due_date_precision,
               a.due_date_raw, a.values_verified
        FROM action_items a JOIN reports r USING (document_id) ORDER BY r.customer_name, a.id""",
    "issues": """
        SELECT d.file_name, r.customer_name, s.severity, s.field, s.reason
        FROM issues s JOIN documents d ON d.id = s.document_id LEFT JOIN reports r ON r.document_id = d.id
        ORDER BY CASE s.severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, d.file_name""",
}


class Repository:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def save_record(self, r: QbrRecord) -> int:
        with self.conn:  # one transaction per document
            doc_id = self._insert_document(
                r.file_name, r.file_hash, "needs_review" if r.needs_review else "success", None,
                r.model, r.prompt_version, r.processed_at.isoformat(), r.model_dump_json(),
            )
            self.conn.execute(
                "INSERT INTO reports VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (doc_id, r.customer.name, r.customer.status, r.period.label, r.period.year, r.period.quarter,
                 _iso(r.period.start), _iso(r.period.end), r.period.status,
                 _iso(r.report_date.value), r.report_date.precision, r.executive_summary),
            )
            self.conn.executemany(
                "INSERT INTO report_items (document_id, item_type, description, scope, status, source_quote,"
                " quote_verified) VALUES (?,?,?,?,?,?,?)",
                [(doc_id, i.item_type, i.description, i.scope, i.status, i.source_quote, i.quote_verified)
                 for i in r.items],
            )
            self.conn.executemany(
                "INSERT INTO kpis (document_id, name, value_raw, value_num, unit, is_approximate, comparator,"
                " previous_raw, previous_num, target_raw, target_num, target_comparator, target_met, source_quote,"
                " quote_verified, values_verified) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(doc_id, k.name, k.value_raw, k.value_num, k.unit, k.is_approximate, k.comparator,
                  k.previous_raw, k.previous_num, k.target_raw, k.target_num, k.target_comparator, k.target_met,
                  k.source_quote, k.quote_verified, k.values_verified) for k in r.kpis],
            )
            self.conn.executemany(
                "INSERT INTO action_items (document_id, description, owner, owner_raw, due_date,"
                " due_date_precision, due_date_raw, source_quote, quote_verified, values_verified)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(doc_id, a.description, a.owner, a.owner_raw, _iso(a.due_date), a.due_date_precision,
                  a.due_date_raw, a.source_quote, a.quote_verified, a.values_verified) for a in r.action_items],
            )
            self.conn.executemany(
                "INSERT INTO issues (document_id, field, severity, reason) VALUES (?,?,?,?)",
                [(doc_id, i.field, i.severity, i.reason) for i in r.issues],
            )
        return doc_id

    def save_failure(self, file_name: str, file_hash: str, error: str, model: str | None,
                     prompt_version: str | None, processed_at: str) -> int:
        with self.conn:
            return self._insert_document(file_name, file_hash, "failed", error, model, prompt_version,
                                         processed_at, None)

    def _insert_document(self, file_name, file_hash, status, error, model, prompt_version, processed_at,
                         record_json) -> int:
        # Replace any previous result for the same file; child rows go via ON DELETE CASCADE.
        self.conn.execute("DELETE FROM documents WHERE file_hash = ?", (file_hash,))
        cur = self.conn.execute(
            "INSERT INTO documents (file_name, file_hash, status, error, model, prompt_version, processed_at,"
            " record_json) VALUES (?,?,?,?,?,?,?,?)",
            (file_name, file_hash, status, error, model, prompt_version, processed_at, record_json),
        )
        return cur.lastrowid

    def find_documents(self, term: str) -> list[tuple[int, str, str, str | None, str | None]]:
        """Look up by id or by part of the file name -> (id, file_name, status, error, record_json)."""
        if term.isdigit():
            sql, arg = "SELECT id, file_name, status, error, record_json FROM documents WHERE id = ?", int(term)
        else:
            sql, arg = "SELECT id, file_name, status, error, record_json FROM documents WHERE file_name LIKE ?", f"%{term}%"
        return self.conn.execute(sql + " ORDER BY file_name", (arg,)).fetchall()

    def export_excel(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(path) as writer:
            for sheet, query in EXPORT_QUERIES.items():
                pd.read_sql_query(query, self.conn).to_excel(writer, sheet_name=sheet, index=False)


def _iso(d) -> str | None:
    return d.isoformat() if d else None
