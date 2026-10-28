"""Checks that text returned by the LLM actually appears in the source document.

This is the main hallucination guard: a quote or value that cannot be found in the
document is flagged for review. Matching is done on normalized text (markdown symbols
stripped, whitespace collapsed, case-folded) and tolerates small differences such as
a dropped period.
"""

import re
from difflib import SequenceMatcher

_MD_RE = re.compile(r"[*_`#|>]+")
_TRANSLATE = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})


def normalize_for_match(text: str) -> str:
    text = text.translate(_TRANSLATE).lower()
    text = _MD_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


class Grounding:
    def __init__(self, document_text: str, threshold: float = 0.85):
        self._doc = normalize_for_match(document_text)
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
