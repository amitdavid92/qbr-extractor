"""Normalized record: the final per-document output that gets stored.

build_record() combines the LLM extraction with deterministic normalization,
grounding checks and review rules. It does no I/O and makes no LLM calls.
"""

from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, computed_field

from .grounding import Grounding
from .normalize import ParsedNumber, is_no_value, normalize_owner, parse_date, parse_number, parse_period
from .pdf_reader import PdfDocument
from .schema import QbrExtraction

Severity = Literal["info", "warning", "error"]
ItemType = Literal["goal", "achievement", "challenge", "risk"]


class Issue(BaseModel):
    field: str
    severity: Severity  # warning/error -> document needs human review
    reason: str


class CustomerInfo(BaseModel):
    name: str | None
    status: str
    source_quote: str | None
    quote_verified: bool


class PeriodInfo(BaseModel):
    label: str | None
    status: str
    year: int | None
    quarter: int | None
    start: date | None
    end: date | None
    source_quote: str | None
    quote_verified: bool


class ReportDateInfo(BaseModel):
    raw: str | None
    value: date | None
    precision: str | None


class ReportItem(BaseModel):
    item_type: ItemType
    description: str
    scope: str | None = None  # goals only: current / next
    status: str
    source_quote: str
    quote_verified: bool


class KpiRecord(BaseModel):
    name: str
    value_raw: str | None
    value_num: float | None
    unit: str | None
    is_approximate: bool
    comparator: str | None
    previous_raw: str | None
    previous_num: float | None
    target_raw: str | None
    target_num: float | None
    target_comparator: str | None
    target_met: bool | None  # null unless the target states a direction ("above 800", "below 2%")
    source_quote: str
    quote_verified: bool
    values_verified: bool  # every raw value appears in the document


def target_met(value: ParsedNumber, target: ParsedNumber) -> bool | None:
    """Only judged when the target states its direction. A bare target such as "700" could mean
    at least or at most (users vs. tickets), so it is left as null rather than guessed."""
    if value.value is None or target.value is None or value.comparator or target.comparator is None:
        return None
    if value.unit and target.unit and value.unit != target.unit:
        return None
    v, t = value.value, target.value
    return {">": v > t, ">=": v >= t, "<": v < t, "<=": v <= t}[target.comparator]


class ActionRecord(BaseModel):
    description: str
    owner: str | None
    owner_raw: str | None
    due_date: date | None
    due_date_precision: str | None
    due_date_raw: str | None
    source_quote: str
    quote_verified: bool
    values_verified: bool


class ConflictRecord(BaseModel):
    topic: str
    values: list[str]
    source_quotes: list[str]


class QbrRecord(BaseModel):
    file_name: str
    file_hash: str
    model: str
    prompt_version: str
    processed_at: datetime
    customer: CustomerInfo
    period: PeriodInfo
    report_date: ReportDateInfo
    executive_summary: str
    items: list[ReportItem]
    kpis: list[KpiRecord]
    action_items: list[ActionRecord]
    conflicts: list[ConflictRecord]
    issues: list[Issue]

    @computed_field
    @property
    def needs_review(self) -> bool:
        return any(i.severity != "info" for i in self.issues)


def build_record(doc: PdfDocument, ex: QbrExtraction, model: str, prompt_version: str) -> QbrRecord:
    g = Grounding(doc.text)
    issues: list[Issue] = []

    def issue(field: str, severity: Severity, reason: str) -> None:
        issues.append(Issue(field=field, severity=severity, reason=reason))

    def check_quote(field: str, quote: str | None) -> bool:
        ok = g.contains(quote)
        if quote and not ok:
            issue(field, "warning", f"source quote not found in document: {quote!r}")
        return ok

    def check_values(field: str, *values: str | None) -> bool:
        # Explicit "unknown" markers (TBD, Not recorded) are not claims, so they are not checked.
        missing = [v for v in values if not is_no_value(v) and not g.contains(v)]
        for v in missing:
            issue(field, "warning", f"value not found in document (possible hallucination): {v!r}")
        return not missing

    # --- customer
    c = ex.customer_name
    customer = CustomerInfo(
        name=c.value, status=c.status, source_quote=c.source_quote,
        quote_verified=check_quote("customer_name", c.source_quote),
    )
    if not c.value:
        issue("customer_name", "error", "customer name not found")
    elif c.status == "inferred":
        issue("customer_name", "info", "customer name was inferred")

    # --- period
    p = ex.reporting_period
    parsed = parse_period(p.value)
    period = PeriodInfo(
        label=p.value, status=p.status, year=parsed.year, quarter=parsed.quarter,
        start=parsed.start, end=parsed.end, source_quote=p.source_quote,
        quote_verified=check_quote("reporting_period", p.source_quote),
    )
    if not p.value:
        issue("reporting_period", "error", "reporting period not found")
    else:
        if p.status == "inferred":
            issue("reporting_period", "info", f"period inferred from: {p.source_quote!r}")
        if parsed.year is None:
            issue("reporting_period", "warning", f"year of reporting period is not stated ({p.value!r})")
        if parsed.quarter is None:
            issue("reporting_period", "warning", f"period does not map to a calendar quarter ({p.value!r})")

    # --- report date (year falls back to the period year)
    rd_raw = ex.report_date.value
    rd = parse_date(rd_raw, default_year=parsed.year)
    report_date = ReportDateInfo(raw=rd_raw, value=rd.value if rd else None, precision=rd.precision if rd else None)
    if rd_raw:
        check_quote("report_date", ex.report_date.source_quote)
    default_year = parsed.year or (rd.value.year if rd else None)

    # --- goals, achievements, challenges, risks
    items: list[ReportItem] = []
    for goal in ex.goals:
        items.append(ReportItem(item_type="goal", description=goal.description, scope=goal.scope, status="found",
                                source_quote=goal.source_quote, quote_verified=check_quote("goals", goal.source_quote)))
    for item_type, findings in (("achievement", ex.achievements), ("challenge", ex.challenges), ("risk", ex.risks)):
        for f in findings:
            items.append(ReportItem(item_type=item_type, description=f.description, status=f.status,
                                    source_quote=f.source_quote, quote_verified=check_quote(f"{item_type}s", f.source_quote)))

    if not any(i.item_type == "goal" and i.scope == "current" for i in items):
        issue("goals", "info", "no goals for the reporting period found")
    if not any(i.item_type == "risk" for i in items):
        issue("risks", "info", "no risks found")
    elif all(i.status == "inferred" for i in items if i.item_type == "risk"):
        issue("risks", "info", "risks are inferred; the document has no explicit risk statement")

    # --- KPIs
    kpis: list[KpiRecord] = []
    for k in ex.kpis:
        cur, prev, tgt = parse_number(k.value_raw), parse_number(k.previous_value_raw), parse_number(k.target_raw)
        kpis.append(KpiRecord(
            name=k.name, value_raw=k.value_raw, value_num=cur.value, unit=cur.unit,
            is_approximate=cur.is_approximate, comparator=cur.comparator,
            previous_raw=k.previous_value_raw, previous_num=prev.value,
            target_raw=k.target_raw, target_num=tgt.value, target_comparator=tgt.comparator,
            target_met=target_met(cur, tgt),
            source_quote=k.source_quote, quote_verified=check_quote("kpis", k.source_quote),
            values_verified=check_values(f"kpis[{k.name}]", k.value_raw, k.previous_value_raw, k.target_raw),
        ))
    if not kpis:
        issue("kpis", "warning", "no KPIs found")

    # --- action items
    actions: list[ActionRecord] = []
    for a in ex.action_items:
        due = parse_date(a.due_date_raw, default_year=default_year)
        owner = normalize_owner(a.owner_raw)
        if due:
            for note in due.assumptions:
                issue(f"action_items[{a.description}]", "info", f"due date {a.due_date_raw!r}: {note}")
            if rd and due.value < rd.value:
                issue(f"action_items[{a.description}]", "warning",
                      f"due date {due.value} is before the report date {rd.value}")
        elif not is_no_value(a.due_date_raw):
            issue(f"action_items[{a.description}]", "info", f"could not resolve due date {a.due_date_raw!r}")
        actions.append(ActionRecord(
            description=a.description, owner=owner, owner_raw=a.owner_raw,
            due_date=due.value if due else None, due_date_precision=due.precision if due else None,
            due_date_raw=a.due_date_raw, source_quote=a.source_quote,
            quote_verified=check_quote("action_items", a.source_quote),
            values_verified=check_values(f"action_items[{a.description}]", a.owner_raw, a.due_date_raw),
        ))
    if not actions:
        issue("action_items", "warning", "no action items found")

    # --- conflicts
    conflicts = [ConflictRecord(topic=cf.topic, values=cf.values, source_quotes=cf.source_quotes) for cf in ex.conflicts]
    for cf in conflicts:
        issue("conflicts", "warning", f"conflicting values for {cf.topic}: {' vs '.join(cf.values)}")
        for q in cf.source_quotes:
            check_quote("conflicts", q)

    return QbrRecord(
        file_name=doc.path.name, file_hash=doc.file_hash, model=model, prompt_version=prompt_version,
        processed_at=datetime.now(timezone.utc), customer=customer, period=period, report_date=report_date,
        executive_summary=ex.executive_summary, items=items, kpis=kpis, action_items=actions,
        conflicts=conflicts, issues=issues,
    )
