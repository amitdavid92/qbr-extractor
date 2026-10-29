"""Checks that text returned by the LLM actually appears in the source document.

This is the main hallucination guard: a quote or value that cannot be found in the
document is flagged for review. Matching is done on normalized text (markdown symbols
stripped, whitespace collapsed, case-folded) and tolerates small differences such as
a dropped period.
"""

import re
from difflib import SequenceMatcher

_MD_RE = re.compile(r"[*_`#|>]+")
_BR_RE = re.compile(r"<br\s*/?>", re.I)
_TRANSLATE = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})


def normalize_for_match(text: str) -> str:
    text = _BR_RE.sub(" ", text).translate(_TRANSLATE).lower()
    text = _MD_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def table_columns_text(markdown: str) -> str:
    """Markdown tables read column by column.

    A side-by-side box (e.g. "Highlights | Watch items") is converted row by row, so a
    sentence that wraps inside one column is split across rows. Joining each column top
    to bottom restores those sentences for matching.
    """
    columns: list[str] = []
    table: list[list[str]] = []
    for line in markdown.splitlines() + [""]:
        if line.strip().startswith("|"):
            cells = line.strip().strip("|").split("|")
            if not all(re.fullmatch(r"\s*:?-+:?\s*", c) for c in cells):
                table.append(cells)
        elif table:
            width = max(len(r) for r in table)
            columns.extend(" ".join(r[j] for r in table if j < len(r)) for j in range(width))
            table = []
    return "\n".join(columns)


class Grounding:
    def __init__(self, document_text: str, threshold: float = 0.85):
        self._doc = normalize_for_match(document_text + "\n" + table_columns_text(document_text))
        self._threshold = threshold

    def contains(self, snippet: str | None) -> bool:
        if not snippet:
            return False
        s = normalize_for_match(snippet).strip(" .")
        if not s:
            return False
        if s in self._doc:
            return True
        m = SequenceMatcher(None, self._doc, s, autojunk=False).find_longest_match(0, len(self._doc), 0, len(s))
        return m.size / len(s) >= self._threshold
