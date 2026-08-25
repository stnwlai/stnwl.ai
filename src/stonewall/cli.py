"""Command surface for compiling, querying, and verifying evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .bundle import build_bundle, verify_bundle
from .compiler import compile_corpus
from .errors import StonewallError
from .retrieval import query_corpus, verify_citation


def _json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stonewall",
        description="Compile and query a citation-first litigation evidence corpus.",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("examples/corpus"),
        help="Markdown corpus root (default: %(default)s)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="emit a reproducible evidence bundle")
    build.add_argument("--output", type=Path, default=Path("build/reference"))

    verify = subparsers.add_parser("verify", help="verify corpus and bundle parity")
    verify.add_argument("--output", type=Path, default=Path("build/reference"))

    query = subparsers.add_parser("query", help="retrieve cited evidence spans")
    query.add_argument("terms")
    query.add_argument("--limit", type=int, default=8)
    query.add_argument("--verify-citations", action="store_true")

    return parser


def run(args: argparse.Namespace) -> int:
    corpus_root = args.corpus.resolve()
    if args.command == "build":
        _json(build_bundle(corpus_root, args.output))
        return 0
    if args.command == "verify":
        _json(verify_bundle(corpus_root, args.output))
        return 0
    corpus = compile_corpus(corpus_root)
    if args.command == "query":
        hits = query_corpus(corpus, args.terms, limit=args.limit)
        if args.verify_citations:
            for hit in hits:
                verify_citation(corpus_root, hit.citation)
        _json({"query": args.terms, "count": len(hits), "hits": [hit.to_dict() for hit in hits]})
        return 0
    raise StonewallError(f"unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except StonewallError as exc:
        print(f"stonewall: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
