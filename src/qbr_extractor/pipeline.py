"""End-to-end orchestration: PDF -> extraction -> normalized record -> database.

A failure in one document is recorded and does not stop the rest of the batch.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .extractor import ExtractionError, Extractor
from .pdf_reader import PdfReadError, file_hash, read_pdf
from .prompt import PROMPT_VERSION
from .record import QbrRecord, build_record
from .storage import Repository

log = logging.getLogger(__name__)


@dataclass
class ProcessResult:
    file_name: str
    status: str  # success / needs_review / failed
    record: QbrRecord | None = None
    error: str | None = None


class Pipeline:
    def __init__(self, extractor: Extractor, repo: Repository):
        self.extractor = extractor
        self.repo = repo

    def process_file(self, path: Path) -> ProcessResult:
        log.info("processing %s", path.name)
        try:
            doc = read_pdf(path)
            extraction = self.extractor.extract(doc)
            record = build_record(doc, extraction, self.extractor.client.model, PROMPT_VERSION)
        except (PdfReadError, ExtractionError) as e:
            return self._fail(path, str(e))
        except Exception as e:  # a bug must not take down the whole batch
            log.exception("%s: unexpected error", path.name)
            return self._fail(path, f"unexpected error: {e!r}")

        self.repo.save_record(record)
        return ProcessResult(path.name, "needs_review" if record.needs_review else "success", record)

    def _fail(self, path: Path, error: str) -> ProcessResult:
        log.error("%s: %s", path.name, error)
        self.repo.save_failure(path.name, file_hash(path), error, self.extractor.client.model,
                               PROMPT_VERSION, datetime.now(timezone.utc).isoformat())
        return ProcessResult(path.name, "failed", error=error)

    def process(self, paths: list[Path]) -> list[ProcessResult]:
        return [self.process_file(p) for p in paths]


def collect_pdfs(inputs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for p in inputs:
        if not p.exists():
            raise FileNotFoundError(f"input not found: {p}")
        files.extend(sorted(p.glob("*.pdf")) if p.is_dir() else [p])
    return files
