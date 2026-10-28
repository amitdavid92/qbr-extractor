"""Extraction schema: the contract between the LLM and the rest of the pipeline.

The LLM returns raw text exactly as written plus a verbatim source quote for every
item. Parsing dates/numbers and deciding what needs human review is done in code
(normalize.py / validate.py), not by the model.
"""

from typing import Literal

from pydantic import BaseModel, Field

FieldStatus = Literal["found", "inferred", "missing"]
ItemStatus = Literal["found", "inferred"]

QUOTE_DESC = (
    "Verbatim, contiguous text copied from the document that supports this value "
    "(a short span, without markdown symbols). Null only if status is 'missing'."
)


class TextField(BaseModel):
    value: str | None = Field(description="The value, or null if not present in the document.")
    status: FieldStatus = Field(
        description="found = stated explicitly; inferred = derived from other content "
        "in the document; missing = not available."
    )
    source_quote: str | None = Field(description=QUOTE_DESC)


class Goal(BaseModel):
    description: str
    scope: Literal["current", "next"] = Field(
        description="current = objective for the reporting period; next = priority/focus "
        "for the upcoming period."
    )
    source_quote: str = Field(description=QUOTE_DESC)


class Kpi(BaseModel):
    name: str
    value_raw: str | None = Field(description="Current-period value exactly as written, e.g. '~900', '1.8M', '4.3 / 5'.")
    previous_value_raw: str | None = Field(description="Previous-period value as written, if given.")
    target_raw: str | None = Field(description="Target for this metric as written, if stated anywhere in the document.")
    source_quote: str = Field(description=QUOTE_DESC)


class Finding(BaseModel):
    description: str
    status: ItemStatus
    source_quote: str = Field(description=QUOTE_DESC)


class ActionItem(BaseModel):
    description: str
    owner_raw: str | None = Field(
        description="Owner exactly as written. If the document explicitly says there is no "
        "owner (e.g. 'Not recorded', 'no owner assigned yet') copy that phrase. Null if not mentioned."
    )
    due_date_raw: str | None = Field(
        description="Due date / target exactly as written (e.g. 'July 2026', 'TBD', "
        "'before end of Q3'). Null if not mentioned."
    )
    source_quote: str = Field(description=QUOTE_DESC)


class Conflict(BaseModel):
    topic: str = Field(description="What the conflicting values describe, e.g. 'June adoption rate'.")
    values: list[str] = Field(description="The differing values as written.")
    source_quotes: list[str] = Field(description="One verbatim quote per value.")


class QbrExtraction(BaseModel):
    customer_name: TextField
    reporting_period: TextField = Field(
        description="The business period the report covers (not the meeting/report date), "
        "in the form 'Q<n> <year>' when it maps to a quarter, otherwise as written."
    )
    report_date: TextField = Field(description="Date the report/meeting was written or held, as written.")
    executive_summary: str = Field(
        description="2-3 sentence neutral summary written by you, based only on the document."
    )
    goals: list[Goal]
    kpis: list[Kpi]
    achievements: list[Finding]
    challenges: list[Finding]
    risks: list[Finding]
    action_items: list[ActionItem]
    conflicts: list[Conflict]
