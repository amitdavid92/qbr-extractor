"""Document text -> validated QbrExtraction, with an on-disk cache of LLM responses.

The cache key is (file hash, prompt version, model), so re-running normalization,
validation or evaluation does not spend API quota, and a prompt change invalidates
old results automatically.
"""

import hashlib
import logging
from pathlib import Path

from pydantic import ValidationError

from .llm import LLMClient, LLMError
from .pdf_reader import PdfDocument
from .prompt import PROMPT_VERSION, SYSTEM_PROMPT, build_user_message
from .schema import QbrExtraction

log = logging.getLogger(__name__)


class ExtractionError(Exception):
    def __init__(self, message: str, raw_response: str | None = None):
        super().__init__(message)
        self.raw_response = raw_response


class Extractor:
    def __init__(self, client: LLMClient, cache_dir: Path | None = None):
        self.client = client
        self.cache_dir = cache_dir

    def extract(self, doc: PdfDocument) -> QbrExtraction:
        cached = self._cache_read(doc)
        if cached is not None:
            return QbrExtraction.model_validate_json(cached)

        user = build_user_message(doc.text)
        raw = self._call(user)
        try:
            result = QbrExtraction.model_validate_json(raw)
        except ValidationError as e:
            # One repair attempt: show the model its own output and the validation error.
            log.warning("%s: schema validation failed, retrying once", doc.path.name)
            repair = (
                f"{user}\n\nYour previous answer did not match the schema.\n"
                f"Previous answer:\n{raw}\n\nValidation error:\n{e}\n\nReturn a corrected answer."
            )
            raw = self._call(repair)
            try:
                result = QbrExtraction.model_validate_json(raw)
            except ValidationError as e2:
                raise ExtractionError(f"invalid model output after retry: {e2}", raw) from e2

        self._cache_write(doc, raw)
        return result

    def _call(self, user: str) -> str:
        try:
            return self.client.generate_json(SYSTEM_PROMPT, user, QbrExtraction)
        except LLMError as e:
            raise ExtractionError(str(e)) from e

    def _cache_path(self, doc: PdfDocument) -> Path | None:
        if self.cache_dir is None:
            return None
        key = hashlib.sha256(f"{doc.file_hash}|{PROMPT_VERSION}|{self.client.model}".encode()).hexdigest()
        return self.cache_dir / f"{key[:32]}.json"

    def _cache_read(self, doc: PdfDocument) -> str | None:
        path = self._cache_path(doc)
        if path is not None and path.exists():
            log.info("%s: using cached LLM response", doc.path.name)
            return path.read_text()
        return None

    def _cache_write(self, doc: PdfDocument, raw: str) -> None:
        path = self._cache_path(doc)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(raw)
