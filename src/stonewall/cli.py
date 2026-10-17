"""Command surface for compiling, querying, auditing, and checking evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from . import transcripts
from .attribution import load_speakers
from .bundle import build_bundle, verify_bundle
from .checks import load_defects, render_registry, run_checks
from .compiler import compile_corpus
from .disclosure import channel_view, load_policy
from .errors import StonewallError, TranscriptError
from .grounding import audit_answer, load_answer
from .layout import CORPUS_DIR, DEFECTS_FILE, POLICY_FILE, SPEAKERS_FILE
from .models import Finding
from .packet import EvidencePacket, build_packet
from .retrieval import query_corpus, resolve_address, verify_citation


def _json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stonewall",
        description="Run the Stonewall evidence demo over synthetic legal records.",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path(CORPUS_DIR),
        help="Markdown corpus root (default: %(default)s)",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path(POLICY_FILE),
        help="disclosure policy file (default: %(default)s)",
    )
    parser.add_argument(
        "--speakers",
        type=Path,
        default=Path(SPEAKERS_FILE),
        help="speaker registry file (default: %(default)s)",
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
    query.add_argument("--channel", default="publish")

    packet = subparsers.add_parser("packet", help="build the evidence packet for a channel")
    packet.add_argument("question")
    packet.add_argument("--channel", required=True)
    packet.add_argument("--limit", type=int, default=8)
    packet.add_argument("--format", choices=("json", "text"), default="json")

    audit = subparsers.add_parser("audit-answer", help="audit an answer against its packet")
    audit.add_argument("path")  # kept raw so transcripts can confine it
    audit.add_argument("--release-to")
    audit.add_argument("--format", choices=("text", "json"), default="text")

    cite = subparsers.add_parser("cite", help="print the verified lines of an address")
    cite.add_argument("address")
    cite.add_argument("--channel", default="publish")

    checks = subparsers.add_parser("checks", help="run every check against its seeded defects")
    checks.add_argument("--repo", type=Path, default=Path("."))
    checks.add_argument("--defects", type=Path)
    checks.add_argument("--only", nargs="+", metavar="NAME")
    checks.add_argument("--list", action="store_true")
    checks.add_argument("--format", choices=("text", "json"), default="text")

    regenerate = subparsers.add_parser("transcripts", help="check or rewrite README transcripts")
    mode = regenerate.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    regenerate.add_argument("document")

    return parser


def _packet_text(packet: EvidencePacket) -> str:
    """Addresses and designations only; never record text."""
    lines = [
        f"packet  {packet.digest[:12]}  channel {packet.channel}"
        f"  limit {packet.limit}  view {packet.view_root[:12]}"
    ]
    lines.extend(
        f"{entry.handle}  {entry.hit.citation.address}  {entry.designation}"
        for entry in packet.entries
    )
    return "\n".join(lines)


def _cite(args: argparse.Namespace, corpus_root: Path) -> int:
    corpus = compile_corpus(corpus_root)
    view = channel_view(corpus, load_policy(args.policy), args.channel)
    citation, span = resolve_address(view, args.address)
    artifact = view.artifact(citation.artifact_id)
    designation = artifact.designation if artifact is not None else ""
    print(f"{citation.address}  {citation.path.as_posix()}  {designation}")
    width = len(str(citation.line_end))
    for number, line in enumerate(span.split("\n"), start=citation.line_start):
        print(f"  {number:>{width}}  {line}".rstrip())
    return 0


def _checks(args: argparse.Namespace) -> int:
    if args.list:
        print(render_registry(load_defects(args.defects or args.repo / DEFECTS_FILE)))
        return 0
    report = run_checks(args.repo.resolve(), defects_path=args.defects, only=args.only)
    if args.format == "json":
        _json(report.to_dict())
    else:
        print(report.render_text())
    return 0 if report.passed else 1


def _transcripts(args: argparse.Namespace) -> int:
    root = Path.cwd()
    document = PurePosixPath(args.document)
    try:
        transcripts.publishable_file(root, args.document)
        if args.write:
            print(f"rewrote {transcripts.write_transcripts(root, document)} block(s)")
            return 0
        findings = transcripts.check_transcripts(root, document)
        if findings:
            for finding in findings:
                print(finding.render())
            return 1
        text = (root / document).read_bytes().decode("utf-8")
        count = len(transcripts.parse_transcripts(text))
    except TranscriptError as exc:
        print(f"stonewall: {Finding(document.as_posix(), exc.line, exc.rule).render()}",
              file=sys.stderr)
        return 2
    print(f"{document.as_posix()}: {count} transcript block(s) current.")
    return 0


def run(args: argparse.Namespace) -> int:
    corpus_root = args.corpus.resolve()
    if args.command == "build":
        _json(build_bundle(corpus_root, args.output))
        return 0
    if args.command == "verify":
        _json(verify_bundle(corpus_root, args.output))
        return 0
    if args.command == "checks":
        return _checks(args)
    if args.command == "transcripts":
        return _transcripts(args)
    if args.command == "cite":
        return _cite(args, corpus_root)
    corpus = compile_corpus(corpus_root)
    policy = load_policy(args.policy)
    if args.command == "query":
        view = channel_view(corpus, policy, args.channel)
        hits = query_corpus(view, args.terms, limit=args.limit)
        if args.verify_citations:
            for hit in hits:
                verify_citation(corpus_root, hit.citation)
        _json({
            "channel": args.channel,
            "count": len(hits),
            "hits": [hit.to_dict() for hit in hits],
            "query": args.terms,
        })
        return 0
    if args.command == "packet":
        packet = build_packet(
            corpus, policy, args.question, channel=args.channel, limit=args.limit
        )
        if args.format == "json":
            _json(packet.to_dict())
        else:
            print(_packet_text(packet))
        return 0
    if args.command == "audit-answer":
        path = Path(args.path)
        document = load_answer(path, source=path.as_posix())
        audit = audit_answer(
            document, corpus, policy, load_speakers(args.speakers), release_to=args.release_to
        )
        if args.format == "json":
            _json(audit.to_dict())
        else:
            print(audit.render_text())
        return 0 if audit.ok else 1
    raise StonewallError(f"unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except StonewallError as exc:
        print(f"stonewall: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        # Do not print filesystem paths or data from the underlying exception.
        print(f"stonewall: filesystem_error: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
