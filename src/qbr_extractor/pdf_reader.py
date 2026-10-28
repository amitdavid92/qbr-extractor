"""PDF -> markdown text. Layout-aware so tables survive as markdown tables."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pymupdf
import pymupdf4llm

pymupdf.set_messages(pylogging=True)  # route parser chatter to the `pymupdf` logger instead of stdout


class PdfReadError(Exception):
    """The PDF could not be turned into usable text (corrupt, encrypted, or scanned)."""


@dataclass(frozen=True)
class PdfDocument:
    path: Path
    file_hash: str  # sha256 of the raw bytes; used for idempotency and cache keys
    text: str  # markdown


MIN_TEXT_CHARS = 50  # below this we assume there is no text layer (e.g. a scanned PDF)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_pdf(path: Path) -> PdfDocument:
    digest = file_hash(path)
    try:
        # OCR is off: all inputs are digital PDFs; scanned input fails loudly below instead.
        text = pymupdf4llm.to_markdown(str(path), use_ocr=False)
    except Exception as e:
        raise PdfReadError(f"failed to parse PDF: {e}") from e

    if len(text.strip()) < MIN_TEXT_CHARS:
        # OCR / vision fallback is a documented extension, not part of the PoC.
        raise PdfReadError("no text layer found (scanned PDF?)")

    return PdfDocument(path=path, file_hash=digest, text=text)
