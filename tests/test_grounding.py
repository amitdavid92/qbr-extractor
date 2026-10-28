from qbr_extractor.grounding import Grounding

DOC = """
## **Actions**

|**Item**|**Owner**|**Target**|
|---|---|---|
|Poland rollout readiness review|Not recorded|August 2026|

- Adoption was described during the meeting as "around seventy percent."
"""


def test_exact_and_markdown_insensitive():
    g = Grounding(DOC)
    assert g.contains("Poland rollout readiness review")
    assert g.contains("Poland rollout readiness review Not recorded August 2026")  # across table cells
    assert g.contains("ACTIONS")


def test_tolerates_small_differences():
    g = Grounding(DOC)
    assert g.contains("Adoption was described during the meeting as “around seventy percent”")


def test_rejects_invented_text():
    g = Grounding(DOC)
    assert not g.contains("Owner: Michael Brown")
    assert not g.contains("Germany rollout completed in March")
    assert not g.contains(None)
    assert not g.contains("")
