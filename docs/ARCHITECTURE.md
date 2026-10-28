# Architecture and decisions

## The problem

The hard part is not reading the PDF. It is the **semantics**:
- The same concept appears under different headings: "Highlights", "What went well" and "Main achievements" all mean achievements.
- Each value has to be classified as stated, inferred, missing or contradicted.
- Every value has to be normalized so it can be queried.

The biggest risk is an LLM that fills empty fields "helpfully", for example with an owner, a date or a risk that is not in the document. A user who cannot trust the output will re-check everything by hand, and then the tool has saved nothing.

The design therefore splits the work:
- **The LLM does what only it can do:** map meaning to a fixed schema.
- **Deterministic code does everything that can be checked:** normalization, grounding, review rules and storage.

## Flow

```
            ┌─────────────┐   markdown   ┌──────────────────────┐  JSON (raw values   ┌───────────────────────────┐
 PDF ──────►│ pdf_reader  │─────────────►│ extractor + llm      │  + source quotes)   │ record.build_record       │
            │ pymupdf4llm │              │ schema-constrained,  │────────────────────►│ normalize  dates/numbers  │
            └─────────────┘              │ temp 0, cached       │                     │ grounding  quote in text? │
                  │ no text layer        └──────────────────────┘                     │ rules      -> issues      │
                  ▼                              │ invalid JSON → 1 repair call         └─────────────┬─────────────┘
              failed (recorded)                  ▼ still invalid                                    │ QbrRecord
                                             failed (recorded)                                      ▼
                                                                                    storage: SQLite ──► Excel export
                                                                                                    │
                                                                       qbr show · Streamlit · eval ◄┘
```

| Step | Module | Key point |
|---|---|---|
| Read | `pdf_reader` | Converts the PDF to markdown with pymupdf4llm. Markdown keeps tables and headings, which helps the LLM with two-column KPI tables. If almost no text is found, it fails explicitly as "no text layer (scanned PDF?)" rather than sending empty text to the LLM. |
| Extract | `extractor`, `llm`, `prompt`, `schema` | One call per document. `response_schema` is the Pydantic model, temperature is 0, and the LLM returns **raw values exactly as written** plus a **verbatim `source_quote`** for each item. The output is validated against the schema. If it fails, there is one repair call with the error message, and if that also fails the document is marked failed. |
| Normalize | `normalize` | Pure functions turn `"~70%"`, `"1.8M"`, `"15/07/26"`, `"before end of Q3"`, `"Apr–Jun"` and `"TBD"` into typed values. Each also records an assumption note when it had to make one. |
| Verify | `grounding` | Every quote, and every owner, date and KPI value, is searched for in the document text. The match is exact after normalization, with a fuzzy fallback. A value that does not appear becomes a "possible hallucination" warning. |
| Review rules | `record` | Rules turn uncertainty into `issues` with severity `info`, `warning` or `error`. A document gets `needs_review` when it has at least one warning or error. |
| Store | `storage` | SQLite with one row per document plus child tables. Re-processing the same file (identified by its hash) replaces that document's rows inside one transaction. Excel is an export of the database. |

## Main decisions

### 1. A pipeline, not an agent
The task has one well-defined step: one document in, one schema out. An agent with tools would add non-determinism, cost and things to debug, and nothing in the task needs dynamic decisions. A single schema-constrained call per document is enough. The engineering effort goes into validation and evaluation instead.

### 2. The LLM extracts and code decides
The LLM returns strings exactly as they appear in the document. Code parses the dates and numbers and decides what needs review. Reasons:
- Parsing `"01/08/26"` or `"before end of Q3"` is deterministic and testable. Asking an LLM to do it would hide those assumptions.
- The raw value is kept next to the parsed one (`due_date_raw` and `due_date`), so nothing is lost and every result can be audited.
- Review rules live in code, where they are explicit and can be changed and tested without touching the prompt.

### 3. Confidence comes from verification, not self-reporting
I did not ask the LLM for a confidence score, because self-reported LLM confidence is poorly calibrated. Uncertainty comes from signals that can be checked:

| Signal | Meaning |
|---|---|
| `status`: found, inferred or missing | What the document says. The LLM sets it under strict rules. |
| `quote_verified` and `values_verified` | Whether the quote and the values were found in the source text. Code checks this. |
| Normalization assumptions | For example "01/08 read as DD/MM", or "no year, so the due date was not resolved". |
| `conflicts` | The document contradicts itself. Both values are kept, and neither one is chosen silently. |

Each signal becomes an issue with a severity and a human-readable reason. This is how the system flags "missing, unclear or not confident" information, with a reason a reviewer can act on.

### 4. Gemini free tier, behind an interface
Gemini was chosen because the assignment allowed AI and asked for zero cost. Structured output (`response_schema`) removes most JSON-parsing problems. All model access goes through the `LLMClient` protocol (`generate_json(system, user, schema)`), so switching to Claude, OpenAI or a local model means one new class. Tests run offline against a fake client.

### 5. SQLite plus an Excel export
The assignment says "any database, including Excel". Downstream use means search and analysis, which needs typed, relational data: for example "all actions without an owner" or "KPIs below target by quarter". So the source of truth is SQLite, which has no server and is a single file. Excel is generated from it for business users. `record_json` stores the full record for audit and re-processing.

Tables: `documents`, `reports`, `report_items` (goals, achievements, challenges and risks), `kpis`, `action_items` and `issues`.

### 6. Caching and versioning
The cache key is the file hash plus the prompt version plus the model. Results are reproducible, re-runs and evaluations cost nothing, and every stored record says which prompt and model produced it. Changing the prompt requires bumping `PROMPT_VERSION`.

### 7. Measured, not "looks good"
`qbr eval` compares results against hand-written ground truth. It measures:
- precision and recall per list;
- field accuracy;
- **invented values**, meaning fields that are null in the ground truth but filled in the output. This is the main hallucination metric;
- conflict detection, including false alarms.

Matching is deliberately tolerant of paraphrasing:
- list items match on keyword overlap (description or quote);
- KPI names match strictly;
- each predicted item is paired with at most one ground-truth item.

Because I wrote the ground truth for the 6 samples after seeing the first model output, I also built **a held-out set of 3 new documents**. Its ground truth was written *before* any model run, and its layouts were designed to break assumptions: fiscal year, an email instead of a report, a half-year period, two columns, owner initials with a legend, and a conflict hidden in an appendix. See [ASSUMPTIONS.md](ASSUMPTIONS.md).

## Results

Sample set, prompt v1, `gemini-3.5-flash` (`eval/results/ground_truth_v1.json`):

| Metric | Result |
|---|---|
| List recall | 100% for all 6 lists |
| List precision | goals 93.8%, challenges 93.8%, others 100% |
| KPI value, previous and target | 100% (38 KPIs) |
| Action owner and due date | 100% (21 actions) |
| Invented values | **0 of 85** null slots |
| Conflicts | 2 of 2 detected, 1 false alarm |
| Customer name | 5 of 6 (all-caps title copied) |

The remaining v1 errors led to four general rules in prompt v2: name casing, rounding is not a conflict, risks are not goals, and requests are not challenges. *v2 sample and held-out results: to be added.*

## Limitations and what I would do next

| Limitation | Next step |
|---|---|
| Scanned PDFs are rejected, not read | OCR fallback, or a vision model for pages with no text layer |
| Complex layouts (multi-column boxes, `<br>` in table cells) can degrade the text | Send the page image together with the text to a multimodal model when the layout is complex |
| Grounding proves the *quote* exists, not that the *description* is faithful to it | An LLM-as-judge or entailment check between description and quote |
| Grounding is weak for short numbers ("12" appears everywhere) | Check the number appears inside its own quote, not just anywhere in the document |
| Executive summary is generated and not evaluated | A rubric-based LLM judge |
| No fiscal-calendar configuration | A per-customer fiscal year start |
| `target_met` is judged only when the target has an explicit comparator | Let the LLM state the KPI direction (higher or lower is better), marked as inferred |
| One document per call, sequential | A batch queue for scale. The cache and per-file failure isolation already fit that model. |
| 9 evaluation documents | Grow the ground truth from reviewer corrections in production, so the review queue becomes the evaluation set |

In production, the review queue is the product: reviewers fix only the flagged fields, and each correction becomes ground truth.
