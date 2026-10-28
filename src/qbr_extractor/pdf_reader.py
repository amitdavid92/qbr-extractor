"""PDF -> markdown text. Layout-aware so tables survive as markdown tables."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pymupdf4llm


class PdfReadError(Exception):
    """The PDF could not be turned into usable text (corrupt, encrypted, or scanned)."""


@dataclass(frozen=True)
class PdfDocument:
    path: Path
    file_hash: str  # sha256 of the raw bytes; used for idempotency and cache keys
    text: str  # markdown


MIN_TEXT_CHARS = 50  # below this we assume there is no text layer (e.g. a scanned PDF)


def read_pdf(path: Path) -> PdfDocument:
    data = path.read_bytes()
    file_hash = hashlib.sha256(data).hexdigest()
    try:
        text = pymupdf4llm.to_markdown(str(path))
    except Exception as e:
        raise PdfReadError(f"failed to parse PDF: {e}") from e

    if len(text.strip()) < MIN_TEXT_CHARS:
        # OCR / vision fallback is a documented extension, not part of the PoC.
        raise PdfReadError("no text layer found (scanned PDF?)")

    return PdfDocument(path=path, file_hash=file_hash, text=text)
