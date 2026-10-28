"""Human-readable rendering of one stored record (used by `qbr show`)."""

from .record import QbrRecord

OK, BAD = "✓", "✗"


def _mark(verified: bool) -> str:
    return OK if verified else BAD


def _v(value) -> str:
    return "-" if value is None or value == "" else str(value)


def format_record(r: QbrRecord) -> str:
    out: list[str] = []
    add = out.append
    status = "NEEDS REVIEW" if r.needs_review else "OK"
    add(f"═══ {r.file_name} ═══  [{status}]   model={r.model} prompt={r.prompt_version}")
    add("")
    c, p, d = r.customer, r.period, r.report_date
    add(f"Customer    : {_v(c.name)}  ({c.status}) {_mark(c.quote_verified)} {_v(c.source_quote)!r}")
    period = f"Q{p.quarter} {p.year or '????'}" if p.quarter else _v(p.label)
    span = f"  {p.start} → {p.end}" if p.start else ""
    add(f"Period      : {period}{span}  ({p.status}, as written: {_v(p.label)!r}) {_mark(p.quote_verified)}")
    add(f"Report date : {_v(d.value)}  ({_v(d.precision)}, as written: {_v(d.raw)!r})")
    add("")
    add("Executive summary (generated):")
    add(f"  {r.executive_summary}")

    labels = {"goal": "GOALS", "achievement": "ACHIEVEMENTS", "challenge": "CHALLENGES", "risk": "RISKS"}
    for item_type, title in labels.items():
        items = [i for i in r.items if i.item_type == item_type]
        add("")
        add(f"{title} ({len(items)})")
        for i in items:
            tags = ", ".join(t for t in (i.scope, i.status if i.status != "found" else None) if t)
            add(f"  {_mark(i.quote_verified)} {i.description}" + (f"  [{tags}]" if tags else ""))

    add("")
    add(f"KPIs ({len(r.kpis)})")
    for k in r.kpis:
        approx = " ~approx" if k.is_approximate else ""
        target = f"  target={k.target_raw!r} met={_v(k.target_met)}" if k.target_raw else ""
        prev = f"  prev={k.previous_raw!r}" if k.previous_raw else ""
        add(f"  {_mark(k.values_verified)} {k.name}: {_v(k.value_raw)!r} → {_v(k.value_num)} {k.unit or ''}"
            f"{approx}{prev}{target}")

    add("")
    add(f"ACTION ITEMS ({len(r.action_items)})")
    for a in r.action_items:
        owner = a.owner or f"(none; written: {_v(a.owner_raw)!r})"
        due = f"{a.due_date} ({a.due_date_precision})" if a.due_date else f"(none; written: {_v(a.due_date_raw)!r})"
        add(f"  {_mark(a.values_verified)} {a.description}")
        add(f"      owner: {owner}   due: {due}")

    if r.conflicts:
        add("")
        add(f"CONFLICTS ({len(r.conflicts)})")
        for cf in r.conflicts:
            add(f"  {cf.topic}: {' vs '.join(cf.values)}")

    add("")
    add(f"ISSUES ({len(r.issues)})")
    for i in sorted(r.issues, key=lambda i: ("error", "warning", "info").index(i.severity)):
        add(f"  {i.severity.upper():<7} {i.field}: {i.reason}")
    add("")
    add(f"{OK} = quote/values found in the document   {BAD} = not found (check for hallucination)")
    return "\n".join(out)
