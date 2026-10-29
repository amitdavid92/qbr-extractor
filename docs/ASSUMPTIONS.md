# Assumptions and interpretation rules

The assignment leaves several definitions open. Below is each one I had to make, the rule I chose, and where it is enforced. Each rule can be changed in a single place.

## Scope

| Assumption | Why |
|---|---|
| Input is digital PDFs with a text layer, in English | Matches all sample files. Scans are detected and fail with a clear message instead of producing empty records. |
| A document describes one customer or business unit and one reporting period | Matches all samples. Multi-customer documents are out of scope. |
| This is a PoC with low volume, one user and one machine | That is why it uses SQLite, sequential processing and no authentication. |
| Using AI is allowed, and the LLM must be free | The free Gemini tier is used, behind a replaceable interface. |

## Field definitions

| Field | Rule |
|---|---|
| **Customer / unit** | The full name in normal capitalization, as written in running text or footers ("BluePeak Financial Services", not "BLUEPEAK"). When a report is about a sub-unit, the unit is part of the name ("Kestrel Energy – Retail Division"). A consultant or author is never the customer. |
| **Period** | The period whose results are reviewed. This is **not** the date the report was written: Globex is dated July but reviews Apr–Jun. It is normalized to a calendar year, quarter, start and end. |
| **Executive summary** | **Always generated** by the model from the document, even when the document has its own summary, so that every record has one in a consistent style. It is labeled "generated" and is the only abstractive field. |
| **Goals** | Objectives for the reviewed period have `scope=current`. "Q3 Focus", "Customer priorities" and similar sections are goals for the **next** period (`scope=next`), kept rather than discarded because they are useful for the next QBR. Risks, dependencies and issues are not goals. |
| **KPIs** | Name, value, previous value and target, each kept **as written** and also parsed into a number and unit. Approximate values (`~`, "around") are flagged as approximate. A value given as a range is kept as text with no number. |
| **target_met** | Computed only when the target has an explicit direction ("above 80%", "at least 700", "under 2h") and the units match. Otherwise it stays empty, because higher-is-better cannot be assumed. |
| **Achievements** | Things completed in the period. Actions from a previous QBR that are marked "Done" count as achievements, not open actions. |
| **Challenges** | Current problems or gaps. Requests and planned work are not challenges; they are actions. |
| **Risks** | Possible future negative outcomes. When the document has no risk section, the model may infer risks clearly implied by the content, **labeled `inferred`**. Inferred risks are not counted in the evaluation, and a report whose risks are all inferred gets an info note. |
| **Action items** | Next steps, agreed activities and follow-ups, including "Next executive review" when it is listed among agreed activities. |
| **Owner** | Copied as written: a person, a team ("Platform Engineering") or initials. When the document has a legend for initials, either form is accepted. **The owner is never guessed from context.** |
| **Due date** | See *Dates* below. |

## Missing, unknown and "no value"

- A missing value is `null`, never an empty string or `"N/A"`. **Null is always preferred to a guess.**
- Explicit placeholders such as "TBD", "TBA", "TBC", "to be agreed", "—", "N/A", "Not recorded", "no owner assigned yet", "unassigned" and "-" are normalized to `null`. The original text is kept in `owner_raw` or `due_date_raw`, so a reviewer can see that the document *said* "TBD" rather than nothing.
- A required field that is missing is flagged:

| Missing | Severity |
|---|---|
| Customer | error |
| Period | error |
| Period year | warning |
| Period quarter | warning |
| KPIs | warning |
| Actions | warning |
| Current-period goals | info |
| Risks | info |

## Dates

| Input | Result |
|---|---|
| `2026-07-15`, `15 July 2026`, `August 5 2026` | That day |
| `01/08/26` | **DD/MM** (international convention), with an "assumed DD/MM" note. If the second part is greater than 12 (`07/15/26`), MM/DD is the only valid reading and is used. |
| `July 2026` | The end of that month, with precision `month` |
| `Q3`, `end of Q3`, `before end of Q3` | The end of that quarter, with precision `quarter` |
| A date with no year (`August 5`) | The **period year** is used. If the document has no year anywhere (BluePeak), the date stays unresolved with an info note, and the raw text is kept. |
| A relative date (`end of next week`) | Not resolved, and kept as raw text |
| A due date earlier than the report date | Warning: probably a typo or a wrongly assumed year |

## Periods

| Input | Result |
|---|---|
| `Q2 2026` | Q2 2026, found |
| `Apr–Jun 2026` | Q2 2026, found. A month range is converted to a quarter only when it lines up exactly with a calendar quarter. |
| A meeting or report date only (`07/07/2026`, `June 30, 2026`) | Inferred as the quarter just reviewed, with status `inferred` and an info note |
| `Q2 / H1`, `H1 2026` | Kept as the label. A half-year has no single quarter, so it gets a warning. |
| `Q3 FY2026` | Should map to the calendar period (Q4 2025 for a fiscal year starting in October). **This is not supported yet.** On the held-out Orion report, it is kept as Q3 with no year and flagged "year not stated" for review. It is never silently converted. |

## Conflicts

A conflict exists when **different sources in the document report different values for the same fact**: for example "68% per the dashboard" against "64% in the meeting", or a goals table against an appendix. Both values and both quotes are stored, the document gets a warning, and **neither value is chosen silently**.

These are not conflicts:
- **Rounding:** "approximately 520" next to the exact "524".
- **An explicit correction:** "correction: 8.7k, not 9.1k" is kept as the corrected value.

## Evaluation assumptions

- The ground truth reflects the rules above. For borderline cases, several answers are accepted (for example "JM" or "Jonas Meyer" when a legend exists).
- Ground truth for the 6 samples was written **after** seeing the first output, so it may be biased. The 3 held-out documents had their ground truth written **before** any model run, and are the more honest measure.
- Customer names are compared ignoring punctuation but **not** ignoring case, so "BLUEPEAK" counts as an error.
- The executive summary is not scored.
