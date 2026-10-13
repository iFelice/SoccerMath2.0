"""CLI per un job fonte di audit_assenze.yml."""
from __future__ import annotations

import argparse
import sys

from .core import write_json
from .policy import EXCLUDED_SOURCES, SOURCE_LABELS, excluded_snapshot
from .runner import run_source


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Legge una fonte autorizzata o registra il motivo di non lettura.")
    parser.add_argument("--source", required=True, choices=sorted(SOURCE_LABELS))
    parser.add_argument("--output", required=True, help="JSON diagnostico del job")
    parser.add_argument("--report-window", default="")
    parser.add_argument("--url", default="")
    parser.add_argument("--authorized", choices=("yes", "no"), default="no")
    parser.add_argument("--history-urls-text", default="", help="Serie A: URL PDF storici, uno per riga")
    parser.add_argument("--history-complete", choices=("yes", "no"), default="no")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.source in EXCLUDED_SOURCES:
        snapshot = excluded_snapshot(args.source, args.report_window)
    else:
        snapshot = run_source(
            args.source,
            url=args.url,
            authorized=args.authorized == "yes",
            report_window=args.report_window,
            history_urls_text=args.history_urls_text,
            history_complete_confirmed=args.history_complete == "yes",
        )
    write_json(args.output, snapshot)
    print(
        f"{args.source}: status={snapshot['status']}; "
        f"HTTP={snapshot.get('http_status')}; bytes={snapshot.get('response_bytes', 0)}; "
        f"document_found={snapshot.get('document_found')}; rows={snapshot.get('rows_extracted', 0)}; "
        f"reason={snapshot.get('reason') or 'n/d'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
