"""Versioned extraction prompt. Bump PROMPT_VERSION on any change: it is part of the
cache key and is stored with every result, so outputs stay traceable to a prompt."""

PROMPT_VERSION = "v2"

# v2 (from v1 eval): normal-case customer names; rounding is not a conflict;
# risks/dependencies are not goals; requests/planned work are not challenges.

SYSTEM_PROMPT = """\
You extract structured data from Quarterly Business Review (QBR) reports.
The document is given as markdown converted from a PDF. Reports differ in layout,
section names and wording; map content by meaning, not by heading.

Core rules:
1. Use only information in the document. Never invent names, dates, numbers or items.
   When something is not in the document, use null (or an empty list). Null is always
   better than a guess.
2. Every extracted item needs source_quote: a short span copied verbatim from the
   document, without markdown symbols such as | or **.
3. status 'found' = stated explicitly. 'inferred' = derived by reasoning from the
   document (for example a quarter derived from a meeting date). Use 'inferred'
   sparingly and only when the document clearly supports it.

Field guidance:
- customer_name: the full name of the customer or business unit. Check headers and footers.
  Write it in normal capitalization as used in running text or footers, not in the
  all-caps styling of a title.
- reporting_period: the period whose results are reviewed, not the date the report was
  written. If only a date is given, infer the period and mark it 'inferred'.
- goals: objectives set for the reporting period (scope 'current'), wherever they
  appear, including narrative text, notes or "objective check" boxes. Priorities or
  focus areas for the upcoming period are goals with scope 'next'. Only include what the
  document presents as an objective, priority or focus; do not turn risks,
  dependencies or issues into goals.
- kpis: quantitative metrics. Copy values exactly as written, including '~', 'around',
  units and percentages. Fill previous_value_raw and target_raw only if the document
  states them.
- achievements: things accomplished in the period.
- challenges: current problems, gaps or issues. Requests and planned work are not
  challenges; they belong in action_items if they are follow-ups.
- risks: possible future negative outcomes. If the document has no risk section,
  you may derive risks that are clearly implied by the content; mark them 'inferred'.
- action_items: next steps, follow-ups, planned or agreed activities. Copy owner and
  due date exactly as written; do not guess an owner from context.
- conflicts: when different sources or measurements in the document report different
  values for the same fact (e.g. a dashboard vs. a meeting statement), list them.
  A rounded or approximate mention of a figure that is also given exactly
  (e.g. "approximately 500" next to "503") is not a conflict.
"""


def build_user_message(document_text: str) -> str:
    return f"<document>\n{document_text}\n</document>"
