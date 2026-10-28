from datetime import date

import pytest

from qbr_extractor.normalize import (
    is_no_value,
    normalize_owner,
    parse_date,
    parse_number,
    parse_period,
)


@pytest.mark.parametrize("raw", [None, "", "TBD", "Not recorded", "no owner assigned yet", "N/A", "unknown", "-"])
def test_no_value_markers(raw):
    assert is_no_value(raw)
    assert normalize_owner(raw) is None


@pytest.mark.parametrize("raw", ["Sarah Levi", "Platform Engineering", "Customer IT team", "Tom"])
def test_real_owners_kept(raw):
    assert normalize_owner(raw) == raw


@pytest.mark.parametrize(
    "raw, default_year, expected, precision",
    [
        ("15 July 2026", None, date(2026, 7, 15), "day"),
        ("June 30, 2026", None, date(2026, 6, 30), "day"),
        ("2026-08-10", None, date(2026, 8, 10), "day"),
        ("July 2026", None, date(2026, 7, 31), "month"),
        ("August 2026", None, date(2026, 8, 31), "month"),
        ("22 July", 2026, date(2026, 7, 22), "day"),
        ("August 5", 2026, date(2026, 8, 5), "day"),
        ("July", 2026, date(2026, 7, 31), "month"),
        ("target before end of Q3", 2026, date(2026, 9, 30), "quarter"),
        ("Q3 2026", None, date(2026, 9, 30), "quarter"),
        ("01/08/26", None, date(2026, 8, 1), "day"),  # DD/MM assumption
        ("07/07/2026", None, date(2026, 7, 7), "day"),
        ("08/25/2026", None, date(2026, 8, 25), "day"),  # second part > 12 -> must be MM/DD
    ],
)
def test_parse_date(raw, default_year, expected, precision):
    parsed = parse_date(raw, default_year)
    assert parsed is not None
    assert parsed.value == expected
    assert parsed.precision == precision


def test_parse_date_records_assumptions():
    assert parse_date("August 5", 2026).assumptions == ("year not stated; assumed 2026",)
    assert parse_date("01/08/26").assumptions == ("ambiguous day/month order; read as DD/MM",)
    assert parse_date("07/07/2026").assumptions == ()  # same day and month: not ambiguous
    assert parse_date("15 July 2026").assumptions == ()


@pytest.mark.parametrize("raw", ["TBD", None, "August 5", "sometime soon", "31/02/2026"])
def test_parse_date_unresolvable(raw):
    # "August 5" without a default year must not silently pick one
    assert parse_date(raw) is None


@pytest.mark.parametrize(
    "raw, year, quarter, start, end",
    [
        ("Q2 2026", 2026, 2, date(2026, 4, 1), date(2026, 6, 30)),
        ("2026 Q2", 2026, 2, date(2026, 4, 1), date(2026, 6, 30)),
        ("April-June 2026", 2026, 2, date(2026, 4, 1), date(2026, 6, 30)),
        ("Q2 Results / H1 Update", None, 2, None, None),  # year genuinely missing
        ("May-July 2026", 2026, None, date(2026, 5, 1), date(2026, 7, 31)),  # not a calendar quarter
        (None, None, None, None, None),
    ],
)
def test_parse_period(raw, year, quarter, start, end):
    p = parse_period(raw)
    assert (p.year, p.quarter, p.start, p.end) == (year, quarter, start, end)


@pytest.mark.parametrize(
    "raw, value, unit, approx, comparator",
    [
        ("875", 875, None, False, None),
        ("1,142", 1142, None, False, None),
        ("74%", 74, "%", False, None),
        ("99.94%", 99.94, "%", False, None),
        ("5.1h", 5.1, "hours", False, None),
        ("42 sec", 42, "seconds", False, None),
        ("1.8M", 1_800_000, None, False, None),
        ("2.4M", 2_400_000, None, False, None),
        ("~900", 900, None, True, None),
        ("around 270", 270, None, True, None),
        ("approximately 600", 600, None, True, None),
        ("~80% adoption", 80, "%", True, None),
        ("more than 2,000", 2000, None, False, ">"),
        ("below 2%", 2, "%", False, "<"),
        ("up to 8 sec", 8, "seconds", False, "<="),
        ("4.3 / 5", 4.3, "/5", False, None),
        ("8.4/10", 8.4, "/10", False, None),
    ],
)
def test_parse_number(raw, value, unit, approx, comparator):
    n = parse_number(raw)
    assert n.value == pytest.approx(value)
    assert (n.unit, n.is_approximate, n.comparator) == (unit, approx, comparator)


@pytest.mark.parametrize("raw", ["110-130", "Rollout not completed", "TBD", None])
def test_parse_number_without_single_value(raw):
    assert parse_number(raw).value is None
