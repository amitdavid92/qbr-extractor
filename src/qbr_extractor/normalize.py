"""Deterministic parsers for the raw strings the LLM copies out of the document.

Every assumption made while parsing (missing year, ambiguous DD/MM order) is returned
alongside the value, so it can be surfaced as an issue instead of silently applied.
"""

import calendar
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

Precision = Literal["day", "month", "quarter"]

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS |= {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
_MONTH = "(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"

# Phrases that mean "this value is explicitly unknown" -> stored as null.
_NO_VALUE_RE = re.compile(
    r"^\s*(tbd|tba|tbc|n/?a|none|unknown|unassigned|[-–—]+"
    r"|to be (agreed|confirmed|determined|decided)"
    r"|not (recorded|assigned|set|defined|agreed|specified)"
    r"|no (owner|date)\b.*)\s*\.?\s*$",
    re.I,
)


def is_no_value(raw: str | None) -> bool:
    return raw is None or not raw.strip() or bool(_NO_VALUE_RE.match(raw))


def normalize_owner(raw: str | None) -> str | None:
    return None if is_no_value(raw) else raw.strip()


# ---------------------------------------------------------------- dates


@dataclass(frozen=True)
class ParsedDate:
    value: date
    precision: Precision
    assumptions: tuple[str, ...] = ()


def _full_year(y: str) -> int:
    n = int(y)
    return n + 2000 if n < 100 else n


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def quarter_bounds(year: int, quarter: int) -> tuple[date, date]:
    return date(year, 3 * quarter - 2, 1), _month_end(year, 3 * quarter)


def parse_date(raw: str | None, default_year: int | None = None) -> ParsedDate | None:
    """Parse a date as written in a report. Partial dates resolve to the end of their
    month/quarter with the matching precision. Returns None when the value is
    explicitly unknown or cannot be resolved (e.g. no year and no default_year)."""
    if is_no_value(raw):
        return None
    s = raw.strip().lower()
    assumptions: list[str] = []

    def year_or_default(y: str | None) -> int | None:
        if y:
            return _full_year(y)
        if default_year is not None:
            assumptions.append(f"year not stated; assumed {default_year}")
        return default_year

    try:
        if m := re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", s):
            return ParsedDate(date(int(m[1]), int(m[2]), int(m[3])), "day")

        if m := re.search(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})\b", s):
            a, b, y = int(m[1]), int(m[2]), _full_year(m[3])
            if b > 12:  # only month-first is possible
                return ParsedDate(date(y, a, b), "day")
            if a <= 12 and a != b:
                assumptions.append("ambiguous day/month order; read as DD/MM")
            return ParsedDate(date(y, b, a), "day", tuple(assumptions))

        if m := re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MONTH},?\s*(\d{{4}})?", s):
            if (y := year_or_default(m[3])) is None:
                return None
            return ParsedDate(date(y, _MONTHS[m[2]], int(m[1])), "day", tuple(assumptions))

        if m := re.search(rf"\b{_MONTH}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b,?\s*(\d{{4}})?", s):
            if (y := year_or_default(m[3])) is None:
                return None
            return ParsedDate(date(y, _MONTHS[m[1]], int(m[2])), "day", tuple(assumptions))

        if m := re.search(rf"\b{_MONTH},?\s*(\d{{4}})?\b", s):
            if (y := year_or_default(m[2])) is None:
                return None
            return ParsedDate(_month_end(y, _MONTHS[m[1]]), "month", tuple(assumptions))

        quarter, qyear = None, None
        if m := re.search(r"\bq([1-4])\b\s*(\d{4})?", s):
            quarter, qyear = int(m[1]), m[2]
        elif m := re.search(r"\b(\d{4})\s*q([1-4])\b", s):
            quarter, qyear = int(m[2]), m[1]
        if quarter:
            if (y := year_or_default(qyear)) is None:
                return None
            return ParsedDate(quarter_bounds(y, quarter)[1], "quarter", tuple(assumptions))
    except ValueError:  # e.g. 31/02
        return None
    return None


# ---------------------------------------------------------------- reporting period


@dataclass(frozen=True)
class Period:
    year: int | None = None
    quarter: int | None = None
    start: date | None = None
    end: date | None = None


def parse_period(raw: str | None) -> Period:
    if not raw:
        return Period()
    s = raw.lower()
    year_m = re.search(r"\b(20\d{2})\b", s)
    year = int(year_m[1]) if year_m else None

    if q := re.search(r"\bq([1-4])\b", s):
        quarter = int(q[1])
        start, end = quarter_bounds(year, quarter) if year else (None, None)
        return Period(year, quarter, start, end)

    if r := re.search(rf"{_MONTH}\s*(?:-|–|to|through)\s*{_MONTH}", s):
        m1, m2 = _MONTHS[r[1]], _MONTHS[r[2]]
        quarter = (m2 // 3) if (m2 - m1 == 2 and m2 % 3 == 0) else None
        if year is None:
            return Period(None, quarter)
        return Period(year, quarter, date(year, m1, 1), _month_end(year, m2))

    return Period(year)


# ---------------------------------------------------------------- numbers


@dataclass(frozen=True)
class ParsedNumber:
    value: float | None
    unit: str | None = None
    is_approximate: bool = False
    comparator: str | None = None  # '>', '<', '<=', '>=' for "more than 2,000" etc.
    notes: tuple[str, ...] = field(default_factory=tuple)


_APPROX_RE = re.compile(r"~|≈|\b(around|approx(imately)?|about|roughly|circa|nearly|almost|estimated)\b", re.I)
_COMPARATORS = [
    (re.compile(r"\b(more than|over|above|greater than|exceeds?)\b", re.I), ">"),
    (re.compile(r"\b(less than|below|under)\b", re.I), "<"),
    (re.compile(r"\b(up to|at most)\b", re.I), "<="),
    (re.compile(r"\b(at least)\b", re.I), ">="),
]
_NUM_RE = re.compile(r"(-?\d[\d,]*(?:\.\d+)?)(?:\s*([kmb])(?![a-z]))?", re.I)
_RANGE_RE = re.compile(r"\d\s*(?:-|–|to)\s*\d")
_MULT = {"k": 1e3, "m": 1e6, "b": 1e9}
_UNITS = [
    (re.compile(r"^\s*%"), "%"),
    (re.compile(r"^\s*/\s*(\d+(?:\.\d+)?)"), None),  # score like "4.3 / 5" -> unit "/5"
    (re.compile(r"^\s*(h|hrs?|hours?)\b", re.I), "hours"),
    (re.compile(r"^\s*(min|mins|minutes?)\b", re.I), "minutes"),
    (re.compile(r"^\s*(ms|milliseconds?)\b", re.I), "ms"),
    (re.compile(r"^\s*(s|secs?|seconds?)\b", re.I), "seconds"),
]


def parse_number(raw: str | None) -> ParsedNumber:
    if is_no_value(raw):
        return ParsedNumber(None)
    approx = bool(_APPROX_RE.search(raw))
    comparator = next((op for rx, op in _COMPARATORS if rx.search(raw)), None)
    if _RANGE_RE.search(raw):
        return ParsedNumber(None, None, approx, comparator, ("range value; not reduced to one number",))
    m = _NUM_RE.search(raw)
    if not m:
        return ParsedNumber(None, None, approx, comparator, ("no numeric value",))

    value = float(m[1].replace(",", "")) * _MULT.get((m[2] or "").lower(), 1)
    rest = raw[m.end():]
    unit = None
    for rx, name in _UNITS:
        if um := rx.match(rest):
            unit = name or f"/{um[1]}"
            break
    return ParsedNumber(value, unit, approx, comparator)
