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


TWO_COLUMN = """
|**Highlights**|**Watch items**|
|---|---|
|Smart-meter portal launched in|Billing failures in April affected ~3,200|
|February.|customers; credits were issued.|

|Action|Owner|Due|
|---|---|---|
|Home line rollout plan|Legal<br>(Kestrel)|March 15,<br>2026|
"""


def test_sentences_wrapped_inside_a_table_column():
    g = Grounding(TWO_COLUMN)
    assert g.contains("Smart-meter portal launched in February.")
    assert g.contains("Billing failures in April affected ~3,200 customers; credits were issued.")
    assert not g.contains("Mobile app released to all customers")


def test_line_breaks_inside_table_cells():
    g = Grounding(TWO_COLUMN)
    assert g.contains("Legal (Kestrel)")
    assert g.contains("March 15, 2026")
