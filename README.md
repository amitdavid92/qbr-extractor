# QBR Extractor

Turns Quarterly Business Review PDFs, which vary in layout and wording, into one consistent structured record per report. The records are stored in SQLite and exported to Excel. Any value that is missing, unclear or not grounded in the document is flagged so a human can review it.

```
PDF ──► text (markdown) ──► LLM (structured JSON + verbatim quotes) ──► code: normalize · ground · review rules ──► SQLite + Excel
```

- **Architecture and main decisions:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Assumptions and interpretation rules:** [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md)

## Quick start

Requirements: Python 3.11+ and a free Gemini API key from https://aistudio.google.com/apikey.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,ui]"          # the 'ui' extra (Streamlit) is optional
cp .env.example .env                # then set GEMINI_API_KEY in .env

qbr process data/input              # extract all sample PDFs -> output/qbr.db + output/qbr.xlsx
```

Example output:

```
FILE                                                 STATUS        CUSTOMER                     PERIOD    ISSUES
01_Northwind_Technologies_Q2_2026.pdf                success       Northwind Technologies       Q2 2026   0
02_Globex_Retail_Apr-Jun_2026.pdf                    needs_review  Globex Retail                Q2 2026   1
04_BluePeak_Financial_Services_Business_Review.pdf   needs_review  BluePeak Financial Services  Q2 ????   1
...
```

`Q2 ????` is deliberate: the BluePeak report never states a year, so the system flags it instead of guessing one. The Globex flag is a real conflict in the report: 68% against 64% adoption.

**Results in brief:** 0 invented values across 9 documents, 100% on KPI values and on action owners and due dates for the sample set, and a held-out set whose ground truth was written before any model run. See [Results](docs/ARCHITECTURE.md#results).

## Commands

| Command | What it does |
|---|---|
| `qbr process <files or folders>` | Extracts each PDF and saves it to the DB, then re-exports Excel. Re-processing a file replaces its earlier rows. |
| `qbr process ... --no-cache` | Forces a fresh LLM call. By default results are cached in `.cache/llm`. |
| `qbr show <id or name>` | Prints one stored record in readable form, e.g. `qbr show vertex`. |
| `qbr export` | Re-exports `output/qbr.xlsx` from the DB. |
| `qbr eval` | Scores the extraction against the hand-written ground truth in `eval/ground_truth`. |
| `qbr eval --input data/holdout --ground-truth eval/holdout_ground_truth` | Scores against the held-out set. |
| `pytest` | Runs the 97 offline tests. No API key is needed. |

Global options: `--db PATH` (default `output/qbr.db`) and `-v` for verbose logging.

## Looking at the results

- **Excel:** `output/qbr.xlsx` has one sheet each for documents, items, kpis, action_items and issues.
- **Review UI (optional):** `streamlit run app/streamlit_app.py` opens http://localhost:8501.
  - **Overview** tab: status counts and the review queue.
  - **Report** tab: each record side by side with the text the model saw. Every item is marked ✅ when it was found in the document or ❌ when it was not.
  - **Upload** tab: process a new PDF.
- **Raw database:** `uvx datasette output/qbr.db`, or any SQLite client.

Example query, listing open actions without an owner:

```sql
SELECT r.customer_name, a.description, a.owner_raw
FROM action_items a JOIN reports r USING (document_id)
WHERE a.owner IS NULL;
```

## Notes on the free tier

The Gemini free tier allows a limited number of requests per day (about 20 for `gemini-3.5-flash` when this was built). The client handles this as follows:
- It retries transient errors (429 and 503) with backoff.
- It stops immediately once the daily quota is used up.
- Only valid results are cached, so a failed run can simply be re-run and only the missing documents call the API again.

You can set a different model with `GEMINI_MODEL` in `.env`.

## Project layout

```
src/qbr_extractor/
  pdf_reader.py   PDF -> markdown text (pymupdf4llm); rejects scans without a text layer
  schema.py       what the LLM must return (Pydantic -> JSON schema)
  prompt.py       versioned system prompt
  llm.py          Gemini client behind a small LLMClient protocol; retries
  extractor.py    LLM call + validation + one repair attempt + cache
  normalize.py    dates, periods, numbers, owners (deterministic, unit-tested)
  grounding.py    "is this quote / value actually in the document?"
  record.py       builds the final record and the review issues
  storage.py      SQLite schema, save, Excel export
  pipeline.py     per-file orchestration; failures are recorded, never fatal
  evaluation.py   scoring against ground truth
  cli.py, view.py command line and text view
app/streamlit_app.py   optional review UI, with no logic of its own
eval/                  ground truth (sample + held-out) and saved scores
data/input, data/holdout   sample PDFs and 3 extra held-out PDFs (scripts/make_holdout.py)
tests/                 offline tests that use a fake LLM client
```
