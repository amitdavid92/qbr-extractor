"""The evaluator must catch known errors; otherwise good scores mean nothing."""

import json

import pytest

from qbr_extractor.evaluation import evaluate_document, name_similarity, similarity
from qbr_extractor.pdf_reader import read_pdf
from qbr_extractor.record import build_record
from qbr_extractor.schema import QbrExtraction

from .test_pipeline import NORTHWIND, NORTHWIND_EXTRACTION

GT = {
    "file": "01_Northwind_Technologies_Q2_2026.pdf",
    "customer_name": "Northwind Technologies",
    "period": {"year": 2026, "quarter": 2, "status": "found"},
    "report_date": None,
    "goals": [{"text": "Complete SSO rollout", "scope": "current"}],
    "kpis": [{"name": "Monthly Active Users", "value": 875, "previous": 640, "target": 800}],
    "achievements": ["SSO implementation completed successfully in May"],
    "challenges": [],
    "risks": ["Low adoption within Operations could impact the planned company-wide rollout in Q3"],
    "action_items": [{"text": "Complete Operations onboarding", "owner": "Sarah Levi", "due_date": "2026-07-15"}],
    "conflicts": [],
    "needs_review": False,
}
DOC = read_pdf(NORTHWIND)


def run(mutate=None):
    data = json.loads(json.dumps(NORTHWIND_EXTRACTION))
    if mutate:
        mutate(data)
    rec = build_record(DOC, QbrExtraction.model_validate(data), "m", "v")
    return evaluate_document(GT, rec)


def test_perfect_extraction_scores_perfectly():
    res = run()
    assert res.errors == []
    assert res.invented.correct == res.invented.total


def test_invented_owner_is_counted():
    def m(d):
        d["action_items"][0]["owner_raw"] = "Michael Brown"
    res = run(m)
    assert any("action_owner" in e for e in res.errors)


def test_invented_previous_value_is_counted():
    gt_kpi = GT["kpis"][0]
    GT["kpis"][0] = {**gt_kpi, "previous": None}
    try:
        res = run()
        assert res.invented.total - res.invented.correct == 1
        assert any(e.startswith("INVENTED kpi previous") for e in res.errors)
    finally:
        GT["kpis"][0] = gt_kpi


def test_missing_and_extra_items_are_reported():
    def m(d):
        d["achievements"] = [{"description": "Opened a new office in Berlin", "status": "found",
                              "source_quote": "Opened a new office in Berlin"}]
    res = run(m)
    assert res.lists["achievements"].recall == 0
    assert res.lists["achievements"].precision == 0


def test_wrong_goal_scope_and_wrong_customer():
    def m(d):
        d["goals"][0]["scope"] = "next"
        d["customer_name"]["value"] = "Northwind"
    res = run(m)
    assert res.fields["goal_scope"].correct == 0
    assert res.fields["customer_name"].correct == 0


def test_inferred_risks_are_not_scored():
    def m(d):
        d["risks"].append({"description": "Made-up risk about budgets", "status": "inferred", "source_quote": "Q2"})
    assert run(m).lists["risks"].precision == 1.0


@pytest.mark.parametrize("a, b, match", [
    ("Increase adoption across store managers", "Increasing adoption across store managers and reducing manual reporting", True),
    ("Reduce manual reporting processes", "Increasing adoption across store managers and reducing manual reporting processes", True),
    ("Complete SSO rollout", "Expand usage to the Operations team", False),
    ("Training sessions for regional managers were completed", "Two hospital locations completed onboarding", False),
])
def test_item_similarity(a, b, match):
    assert (similarity(a, b) >= 0.6) is match


def test_kpi_names_are_matched_strictly():
    assert name_similarity("Users", "Weekly active users") < 0.5
    assert name_similarity("Weekly active users", "Weekly active users") == 1.0
