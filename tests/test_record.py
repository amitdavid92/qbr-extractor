"""build_record() on a hand-written extraction: no LLM involved."""

from datetime import date
from pathlib import Path

from qbr_extractor.pdf_reader import PdfDocument
from qbr_extractor.record import build_record
from qbr_extractor.schema import ActionItem, Conflict, Goal, Kpi, QbrExtraction, TextField

DOC_TEXT = """
# VERTEX / QUARTERLY REVIEW
June 30, 2026
|Users|~900|1,340|
Adoption was described during the meeting as "around seventy percent."
The analytics dashboard reports 67.9% weekly adoption.
|Performance investigation|Engineering|TBD|
|Regional dashboard requirements|Anna|22 July|
FYI: Original target for Q2 was 900 weekly active users.
Vertex Logistics
"""


def make_extraction(**overrides) -> QbrExtraction:
    data = dict(
        customer_name=TextField(value="Vertex Logistics", status="found", source_quote="Vertex Logistics"),
        reporting_period=TextField(value="Q2 2026", status="inferred", source_quote="June 30, 2026"),
        report_date=TextField(value="June 30, 2026", status="found", source_quote="June 30, 2026"),
        executive_summary="Summary.",
        goals=[Goal(description="900 WAU", scope="current", source_quote="Original target for Q2 was 900 weekly active users")],
        kpis=[Kpi(name="Users", value_raw="1,340", previous_value_raw="~900", target_raw=None, source_quote="Users")],
        achievements=[], challenges=[], risks=[],
        action_items=[
            ActionItem(description="Performance investigation", owner_raw="Engineering", due_date_raw="TBD",
                       source_quote="Performance investigation"),
            ActionItem(description="Regional dashboard requirements", owner_raw="Anna", due_date_raw="22 July",
                       source_quote="Regional dashboard requirements"),
        ],
        conflicts=[],
    )
    data.update(overrides)
    return QbrExtraction(**data)


def build(ex: QbrExtraction):
    doc = PdfDocument(path=Path("vertex.pdf"), file_hash="abc", text=DOC_TEXT)
    return build_record(doc, ex, model="test-model", prompt_version="test")


def reasons(record) -> str:
    return " | ".join(f"{i.severity}:{i.reason}" for i in record.issues)


def test_clean_extraction_is_normalized_and_not_flagged():
    r = build(make_extraction())
    assert (r.period.year, r.period.quarter) == (2026, 2)
    assert r.report_date.value == date(2026, 6, 30)
    assert r.kpis[0].value_num == 1340 and r.kpis[0].previous_num == 900
    assert r.kpis[0].values_verified

    perf, dash = r.action_items
    assert perf.owner == "Engineering" and perf.due_date is None  # TBD -> null, not a parse failure
    assert dash.due_date == date(2026, 7, 22) and dash.due_date_precision == "day"
    assert "year not stated; assumed 2026" in reasons(r)
    assert not r.needs_review, reasons(r)


def test_hallucinated_owner_is_flagged():
    ex = make_extraction(action_items=[
        ActionItem(description="Performance investigation", owner_raw="Michael Brown", due_date_raw="TBD",
                   source_quote="Performance investigation"),
    ])
    r = build(ex)
    assert not r.action_items[0].values_verified
    assert r.needs_review
    assert "possible hallucination" in reasons(r)


def test_conflict_requires_review():
    ex = make_extraction(conflicts=[Conflict(
        topic="weekly adoption", values=["around seventy percent", "67.9%"],
        source_quotes=['described during the meeting as "around seventy percent."',
                       "The analytics dashboard reports 67.9% weekly adoption."],
    )])
    r = build(ex)
    assert r.needs_review
    assert "conflicting values for weekly adoption" in reasons(r)


def test_missing_period_year_requires_review():
    r = build(make_extraction(reporting_period=TextField(value="Q2 Results / H1 Update", status="found",
                                                         source_quote="Q2")))
    assert r.period.quarter == 2 and r.period.year is None
    assert r.needs_review


def test_due_date_before_report_date_is_flagged():
    ex = make_extraction(action_items=[
        ActionItem(description="Regional dashboard requirements", owner_raw="Anna", due_date_raw="22 July",
                   source_quote="Regional dashboard requirements"),
    ], report_date=TextField(value="June 30, 2026", status="found", source_quote="June 30, 2026"))
    ok = build(ex)
    assert not ok.needs_review

    late = build(ex.model_copy(update={"report_date": TextField(value="August 15, 2026", status="found",
                                                                 source_quote="June 30, 2026")}))
    assert "before the report date" in reasons(late)
