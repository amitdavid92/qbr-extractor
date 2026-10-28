"""Command line entry point.

    qbr process data/input            # extract every PDF in the folder, save to SQLite + Excel
    qbr process report.pdf --no-cache # force a fresh LLM call
    qbr export                        # re-export Excel from the database
    qbr show vertex                   # print one stored result in readable form
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .extractor import Extractor
from .llm import GeminiClient
from .pipeline import Pipeline, collect_pdfs
from .record import QbrRecord
from .storage import Repository
from .view import format_record

DEFAULT_DB = Path("output/qbr.db")
DEFAULT_EXCEL = Path("output/qbr.xlsx")
DEFAULT_CACHE = Path(".cache/llm")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qbr", description="Extract structured data from QBR PDF reports.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"SQLite database (default: {DEFAULT_DB})")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_process = sub.add_parser("process", help="process PDF files or folders")
    p_process.add_argument("inputs", nargs="+", type=Path)
    p_process.add_argument("--excel", type=Path, default=DEFAULT_EXCEL, help=f"Excel export (default: {DEFAULT_EXCEL})")
    p_process.add_argument("--no-cache", action="store_true", help="always call the LLM")

    p_export = sub.add_parser("export", help="export the database to Excel")
    p_export.add_argument("--excel", type=Path, default=DEFAULT_EXCEL)

    p_show = sub.add_parser("show", help="print one stored result in readable form")
    p_show.add_argument("document", help="document id or part of its file name, e.g. 'vertex'")

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    load_dotenv()

    repo = Repository(args.db)
    try:
        if args.command == "export":
            repo.export_excel(args.excel)
            print(f"Exported {args.db} -> {args.excel}")
            return 0
        if args.command == "show":
            return _show(args.document, repo)
        return _process(args, repo)
    finally:
        repo.close()


def _show(term: str, repo: Repository) -> int:
    matches = repo.find_documents(term)
    if not matches:
        print(f"No document matches {term!r}. Run `qbr process` first.", file=sys.stderr)
        return 2
    if len(matches) > 1:
        print(f"{term!r} matches several documents; use the id:")
        for doc_id, name, status, *_ in matches:
            print(f"  {doc_id:>3}  {name}  [{status}]")
        return 2
    _, name, status, error, record_json = matches[0]
    if status == "failed":
        print(f"{name}: FAILED - {error}")
        return 1
    print(format_record(QbrRecord.model_validate_json(record_json)))
    return 0


def _process(args: argparse.Namespace, repo: Repository) -> int:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY is not set. Copy .env.example to .env and add your key.", file=sys.stderr)
        return 2
    client = GeminiClient(api_key, os.environ.get("GEMINI_MODEL", "gemini-3.5-flash"))
    extractor = Extractor(client, cache_dir=None if args.no_cache else DEFAULT_CACHE)

    try:
        files = collect_pdfs(args.inputs)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 2
    if not files:
        print("No PDF files found.", file=sys.stderr)
        return 2

    results = Pipeline(extractor, repo).process(files)
    repo.export_excel(args.excel)

    print(f"\n{'FILE':<52} {'STATUS':<13} {'CUSTOMER':<28} {'PERIOD':<9} ISSUES")
    for r in results:
        if r.record:
            rec = r.record
            period = f"Q{rec.period.quarter} {rec.period.year or '????'}" if rec.period.quarter else "-"
            flagged = sum(i.severity != "info" for i in rec.issues)
            print(f"{r.file_name:<52} {r.status:<13} {rec.customer.name or '-':<28} {period:<9} {flagged}")
        else:
            print(f"{r.file_name:<52} {r.status:<13} {r.error}")
    print(f"\nSaved to {args.db} and {args.excel}")
    return 1 if any(r.status == "failed" for r in results) else 0


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "google_genai", "pymupdf"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


if __name__ == "__main__":
    sys.exit(main())
