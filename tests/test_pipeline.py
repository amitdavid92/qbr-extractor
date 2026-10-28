"""End-to-end: real PDF -> fake LLM -> SQLite. Deterministic, no network."""

import json
import sqlite3
from pathlib import Path

import pymupdf
import pytest

from qbr_extractor.extractor import Extractor
from qbr_extractor.pipeline import Pipeline
from qbr_extractor.storage import Repository

NORTHWIND = Path(__file__).parent.parent / "data/input/01_Northwind_Technologies_Q2_2026.pdf"

NORTHWIND_EXTRACTION = {
    "customer_name": {"value": "Northwind Technologies", "status": "found", "source_quote": "Northwind Technologies"},
    "reporting_period": {"value": "Q2 2026", "status": "found", "source_quote": "Period Q2 2026"},
    "report_date": {"value": None, "status": "missing", "source_quote": None},
    "executive_summary": "Adoption improved; Operations onboarding lags.",
    "goals": [{"description": "Complete SSO rollout.", "scope": "current", "source_quote": "Complete SSO rollout."}],
    "kpis": [{"name": "Monthly Active Users", "value_raw": "875", "previous_value_raw": "640",
              "target_raw": "above 800", "source_quote": "Monthly Active Users"}],
    "achievements": [{"description": "SSO done", "status": "found",
                      "source_quote": "SSO implementation completed successfully in May."}],
    "challenges": [],
    "risks": [{"description": "Ops adoption risk", "status": "found",
               "source_quote": "Low adoption within Operations could impact the planned company-wide rollout in Q3."}],
    "action_items": [{"description": "Complete Operations onboarding", "owner_raw": "Sarah Levi",
                      "due_date_raw": "15 July 2026", "source_quote": "Complete Operations onboarding"}],
    "conflicts": [],
}


class FakeLLMClient:
    model = "fake-model"

    def __init__(self, *responses: str):
        self.responses = list(responses)
        self.calls = 0

    def generate_json(self, system, user, schema) -> str:
        self.calls += 1
        return self.responses.pop(0)


@pytest.fixture
def repo(tmp_path):
    r = Repository(tmp_path / "test.db")
    yield r
    r.close()


def rows(repo, sql):
    return repo.conn.execute(sql).fetchall()


def test_end_to_end_success(repo):
    client = FakeLLMClient(json.dumps(NORTHWIND_EXTRACTION))
    result = Pipeline(Extractor(client), repo).process_file(NORTHWIND)

    assert result.status == "success", result.record.issues
    assert rows(repo, "SELECT customer_name, period_year, period_quarter FROM reports") == [
        ("Northwind Technologies", 2026, 2)]
    assert rows(repo, "SELECT owner, due_date, due_date_precision FROM action_items") == [
        ("Sarah Levi", "2026-07-15", "day")]
    assert rows(repo, "SELECT value_num, previous_num, target_num, target_met FROM kpis") == [
        (875.0, 640.0, 800.0, 1)]
    assert rows(repo, "SELECT item_type FROM report_items ORDER BY item_type") == [
        ("achievement",), ("goal",), ("risk",)]


def test_reprocessing_is_idempotent(repo):
    for _ in range(2):
        Pipeline(Extractor(FakeLLMClient(json.dumps(NORTHWIND_EXTRACTION))), repo).process_file(NORTHWIND)
    assert rows(repo, "SELECT COUNT(*) FROM documents") == [(1,)]
    assert rows(repo, "SELECT COUNT(*) FROM action_items") == [(1,)]  # old child rows were cascaded away


def test_invalid_json_is_repaired_once(repo):
    client = FakeLLMClient('{"customer_name": "oops"}', json.dumps(NORTHWIND_EXTRACTION))
    result = Pipeline(Extractor(client), repo).process_file(NORTHWIND)
    assert client.calls == 2
    assert result.status == "success"


def test_persistent_invalid_output_is_stored_as_failure(repo):
    client = FakeLLMClient("not json", "still not json")
    result = Pipeline(Extractor(client), repo).process_file(NORTHWIND)
    assert result.status == "failed"
    assert rows(repo, "SELECT status FROM documents") == [("failed",)]


def test_scanned_pdf_fails_without_llm_call(repo, tmp_path):
    blank = tmp_path / "scanned.pdf"
    d = pymupdf.open()
    d.new_page()
    d.save(blank)

    client = FakeLLMClient()
    result = Pipeline(Extractor(client), repo).process_file(blank)
    assert result.status == "failed" and "no text layer" in result.error
    assert client.calls == 0


def test_show_renders_stored_record(repo, capsys):
    from qbr_extractor.record import QbrRecord
    from qbr_extractor.view import format_record

    Pipeline(Extractor(FakeLLMClient(json.dumps(NORTHWIND_EXTRACTION))), repo).process_file(NORTHWIND)
    [(_, _, _, _, record_json)] = repo.find_documents("northwind")
    text = format_record(QbrRecord.model_validate_json(record_json))
    assert "Northwind Technologies" in text
    assert "owner: Sarah Levi" in text and "2026-07-15 (day)" in text
    assert "met=True" in text


def test_cache_avoids_second_llm_call(repo, tmp_path):
    client = FakeLLMClient(json.dumps(NORTHWIND_EXTRACTION))
    pipeline = Pipeline(Extractor(client, cache_dir=tmp_path / "cache"), repo)
    pipeline.process_file(NORTHWIND)
    pipeline.process_file(NORTHWIND)
    assert client.calls == 1
