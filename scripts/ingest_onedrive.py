#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser
from pathlib import Path
from xml.etree import ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PERSONAL_ROOT = Path(os.environ.get("ONEDRIVE_PERSONAL_ROOT", r"C:\Users\<username>\OneDrive"))
DEFAULT_FIRM_ROOT = Path(os.environ.get("ONEDRIVE_FIRM_ROOT", r"C:\Users\<username>\OneDrive - Your Firm Name"))
DEFAULT_CASE_INDEX = REPO_ROOT / "scripts" / "case_index.json"
DEFAULT_MANIFEST = REPO_ROOT / "catalog" / "intake" / "onedrive_ingest_manifest.jsonl"
DEFAULT_REVIEW_QUEUE = REPO_ROOT / "catalog" / "intake" / "onedrive_review_queue.md"
DEFAULT_DERIVATIVE_ROOT = REPO_ROOT / "sources" / "onedrive_ingest"
DEFAULT_MANUAL_OVERRIDES = REPO_ROOT / "catalog" / "intake" / "onedrive_manual_case_overrides.local.json"
LEGACY_MANUAL_OVERRIDES = REPO_ROOT / "catalog" / "intake" / "onedrive_manual_case_overrides.json"

LEGAL_MATTERS_DS_ID = os.environ.get("NOTION_LEGAL_MATTERS_DB", "YOUR_LEGAL_MATTERS_DATABASE_ID")
STONEWALL_ARCHIVE_DS_ID = os.environ.get("NOTION_ARCHIVE_DB", "YOUR_ARCHIVE_DATABASE_ID")
NOTION_API_VERSION = "2025-09-03"

SUPPORTED_EXTENSIONS = {
    ".csv", ".docx", ".eml", ".htm", ".html", ".json", ".log", ".md", ".msg",
    ".pdf", ".ps1", ".rtf", ".txt", ".xlsx", ".xml", ".yaml", ".yml", ".zip",
}
TEXT_EXTENSIONS = {
    ".csv", ".htm", ".html", ".json", ".log", ".md", ".ps1", ".rtf", ".txt",
    ".xml", ".yaml", ".yml",
}
ARCHIVE_CASE_OPTIONS = {
    # Populate with your firm's case names for the Document Archive database.
    # These should match the Case Name values used in your Notion Legal Matters database.
    # Example: "Smith v. Acme", "Jones v. Corp", "Doe v. LLC"
}
ARCHIVE_TAG_OPTIONS = {
    "billing", "chain-of-custody", "client", "depo", "discovery",
    "email", "forensics", "institutional", "narrative", "otter",
    "screenshot", "settlement", "supersedes", "teams", "verbatim",
}
AMBIGUOUS_KEYWORDS = {
    # Add common ambiguous keywords from your case names that could match multiple matters.
    # Example: "alpha", "beta", "gamma", "sample"
}
CASE_CONTEXT_MARKERS = {
    "claim", "complaint", "court", "cme", "depo", "deposition", "disco",
    "discovery", "hearing", "legal hold", "mediation", "motion", "order",
    "plaintiff", "proposal", "rog", "rtp", "rfa", "settlement", "subpoena",
    "sdt", "trial", "carrier", "v.",
}


class IntakeError(RuntimeError):
    pass


class ExtractionUnavailable(IntakeError):
    pass


@dataclass
class CaseRecord:
    id: str
    name: str
    claim: str = ""
    case_number: str = ""
    plaintiff: str = ""
    carrier_driver: str = ""
    legal_hold_status: str = ""
    date_of_loss: str = ""
    date_of_complaint: str = ""
    case_tag: str = ""
    keywords: set[str] = field(default_factory=set)
    compact_claim: str = ""
    compact_case_number: str = ""


@dataclass
class MatchCandidate:
    case_id: str
    case_name: str
    case_tag: str
    score: int
    reasons: list[str]
    claim: str = ""
    case_number: str = ""
    legal_hold_status: str = ""
    date_of_loss: str = ""
    date_of_complaint: str = ""

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "case_name": self.case_name,
            "case_tag": self.case_tag,
            "score": self.score,
            "reasons": self.reasons,
            "claim": self.claim,
            "case_number": self.case_number,
            "legal_hold_status": self.legal_hold_status,
            "date_of_loss": self.date_of_loss,
            "date_of_complaint": self.date_of_complaint,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stonewall OneDrive intake pipeline.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    refresh = subparsers.add_parser("refresh-cases", help="Refresh the local case cache from Legal Matters.")
    refresh.add_argument("--output", default=str(DEFAULT_CASE_INDEX))

    ingest = subparsers.add_parser("ingest", help="Convert OneDrive files into markdown derivatives and a manifest.")
    ingest.add_argument("--input", action="append", help="File or directory to ingest. Repeatable.")
    ingest.add_argument("--root", choices=["all", "personal", "firm"], default="all")
    ingest.add_argument("--glob", action="append", dest="globs", help="Case-insensitive wildcard filter like *Smith*.")
    ingest.add_argument("--since", help="Only ingest files modified on or after YYYY-MM-DD.")
    ingest.add_argument("--limit", type=int, default=25)
    ingest.add_argument("--case-index", default=str(DEFAULT_CASE_INDEX))
    ingest.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    ingest.add_argument("--review-queue", default=str(DEFAULT_REVIEW_QUEUE))
    ingest.add_argument("--derivative-root", default=str(DEFAULT_DERIVATIVE_ROOT))
    ingest.add_argument("--manual-overrides", default=str(DEFAULT_MANUAL_OVERRIDES))
    ingest.add_argument("--overwrite", action="store_true")
    ingest.add_argument("--extensions", nargs="*")
    ingest.add_argument("--dry-run", action="store_true")
    ingest.add_argument("--sync-notion", action="store_true")
    ingest.add_argument("--sync-workers", type=int, default=1, help="Workers for --sync-notion handoff (1-16).")

    sync = subparsers.add_parser("sync-notion", help="Upsert manifest rows into Stonewall Archive.")
    sync.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    sync.add_argument("--limit", type=int, default=25)
    sync.add_argument("--only-unsynced", action="store_true")
    sync.add_argument("--dry-run", action="store_true")
    sync.add_argument("--workers", type=int, default=1, help="Concurrent Notion upsert workers (1-16).")
    sync.add_argument(
        "--dump-payload",
        help="Optional JSONL path for planned Notion create/update operations (sync still runs unless --dry-run is set).",
    )

    report = subparsers.add_parser(
        "report",
        help="Generate a markdown status report for OneDrive ingestion + Notion sync readiness.",
    )
    report.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    report.add_argument("--review-queue", default=str(DEFAULT_REVIEW_QUEUE))
    report.add_argument(
        "--output",
        default=str(REPO_ROOT / "catalog" / "intake" / "onedrive_status_report.md"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "refresh-cases":
            return cmd_refresh_cases(args)
        if args.command == "ingest":
            return cmd_ingest(args)
        if args.command == "sync-notion":
            return cmd_sync_notion(args)
        if args.command == "report":
            return cmd_report(args)
    except IntakeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_refresh_cases(args: argparse.Namespace) -> int:
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        raise IntakeError("NOTION_TOKEN is required for refresh-cases.")

    pages = notion_paginate_data_source(token, LEGAL_MATTERS_DS_ID)
    records = []
    for page in pages:
        props = page.get("properties", {})
        case_name = get_notion_text(props, "Case Name")
        if not case_name:
            continue
        records.append(
            {
                "name": case_name,
                "claim": get_notion_text(props, "Claim Number"),
                "case_number": get_notion_text(props, "Case Number"),
                "plaintiff": get_notion_text(props, "Plaintiff"),
                "carrier_driver": get_notion_text(props, "Carrier Driver"),
                "legal_hold_status": get_notion_select(props, "Legal Hold Status"),
                "date_of_loss": get_notion_date(props, "Date of Loss"),
                "date_of_complaint": get_notion_date(props, "Date of Complaint"),
                "id": page.get("id", ""),
            }
        )

    records.sort(key=lambda item: item["name"].lower())
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Refreshed {len(records)} cases -> {output_path}")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    case_records = load_case_records(Path(args.case_index))
    case_records_by_name = {record.name: record for record in case_records}
    manifest_path = Path(args.manifest)
    derivative_root = Path(args.derivative_root)
    review_path = Path(args.review_queue)
    manual_overrides = load_manual_overrides(Path(args.manual_overrides))
    existing_entries = load_manifest(manifest_path)
    existing_by_path = {entry["original_path"]: entry for entry in existing_entries}

    since_dt = parse_since(args.since) if args.since else None
    extensions = {ext.lower() for ext in args.extensions} if args.extensions else SUPPORTED_EXTENSIONS
    files = collect_input_files(args.input, args.root, args.globs, extensions, since_dt, args.limit)
    if not files:
        print("No files matched the requested scope.")
        return 0

    skipped = 0
    for source_path in files:
        source_path = source_path.resolve()
        file_sha = sha256_file(source_path)
        existing = existing_by_path.get(str(source_path))
        manual_override = manual_overrides.get(str(source_path))
        if (
            existing
            and existing.get("sha256") == file_sha
            and Path(existing.get("derivative_path", "")).exists()
            and not args.overwrite
            and not manual_override_state_changed(existing, manual_override)
        ):
            skipped += 1
            continue

        entry = build_ingest_entry(source_path, derivative_root, case_records, case_records_by_name, manual_override)
        if args.dry_run:
            print(format_preview(entry))
            continue

        write_derivative(entry)
        existing_by_path[str(source_path)] = entry

    if args.dry_run:
        print(f"Dry run complete. Matched {len(files)} files; skipped {skipped} already-current entries.")
        return 0

    merged_entries = list(existing_by_path.values())
    merged_entries.sort(key=lambda item: item["original_path"].lower())
    write_manifest(manifest_path, merged_entries)
    write_review_queue(review_path, merged_entries)
    print(f"Ingested {len(files) - skipped} files, skipped {skipped}, manifest updated -> {manifest_path}")
    print(f"Review queue refreshed -> {review_path}")

    if args.sync_notion:
        sync_args = argparse.Namespace(
            manifest=str(manifest_path),
            limit=args.limit,
            only_unsynced=True,
            dry_run=False,
            workers=getattr(args, "sync_workers", 1),
        )
        return cmd_sync_notion(sync_args)
    return 0


def cmd_sync_notion(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    entries = load_manifest(manifest_path)
    pending = [entry for entry in entries if not args.only_unsynced or not entry.get("notion_page_id")]
    pending = pending[: args.limit]
    requested_workers = getattr(args, "workers", 1)
    workers = max(1, min(requested_workers, 16))
    if workers != requested_workers:
        print(f"Requested workers={requested_workers} adjusted to supported range -> {workers}")
    if not pending:
        print("No manifest rows are waiting to sync.")
        return 0

    token = os.environ.get("NOTION_TOKEN", "").strip()
    dump_payload_path = getattr(args, "dump_payload", None)
    if not token and not args.dry_run and not dump_payload_path:
        raise IntakeError("NOTION_TOKEN is required for sync-notion unless --dry-run or --dump-payload is set.")

    existing: dict[str, str] = {}
    if token and not args.dry_run:
        try:
            existing = fetch_archive_pages_by_file_path(token)
        except IntakeError as exc:
            print(f"Error fetching existing Notion archive pages: {exc}", file=sys.stderr)
            raise

    synced = 0
    sync_items: list[tuple[dict, str | None, dict]] = []
    for entry in pending:
        file_path_key = entry.get("derivative_path") or entry["original_path"]
        source_root = entry.get("source_root", "")
        normalized_key = normalize_path_for_export(file_path_key, source_root)
        page_id = entry.get("notion_page_id") or existing.get(normalized_key) or existing.get(file_path_key)
        props = build_archive_properties(entry)
        sync_items.append((entry, page_id, props))

    if dump_payload_path:
        if not token:
            print(
                "[WARN] NOTION_TOKEN is not set; dump actions cannot look up "
                "existing pages by file path, so create/update decisions in this "
                "plan may be incomplete (rows with notion_page_id will still be "
                "treated as updates)."
            )
        write_sync_plan(Path(dump_payload_path), sync_items)
        print(f"Wrote sync payload plan -> {dump_payload_path}")
        if args.dry_run:
            return 0

    if args.dry_run:
        for entry, page_id, _ in sync_items:
            action = "update" if page_id else "create"
            file_path_key = entry.get("derivative_path") or entry["original_path"]
            print(f"[DRY RUN] {action}: {entry['title']} -> {file_path_key}")
        print(
            f"[DRY RUN] Would sync {len(sync_items)} Stonewall Archive entries "
            f"-> {manifest_path}"
        )
        return 0

    failures = 0
    if workers == 1:
        for entry, page_id, props in sync_items:
            try:
                notion_page_id = sync_archive_entry(token, entry, page_id, props)
            except Exception as exc:
                print(f"Failed syncing {entry.get('title', entry.get('original_path', 'entry'))}: {exc}", file=sys.stderr)
                failures += 1
                continue
            finally:
                time.sleep(0.35)
            entry["notion_page_id"] = notion_page_id
            entry["notion_url"] = f"https://www.notion.so/{notion_page_id.replace('-', '')}"
            entry["synced_at"] = datetime.now().isoformat(timespec="seconds")
            synced += 1
    else:
        _rate_lock = threading.Lock()
        _last_request: list[float] = [0.0]

        def _rate_limited_sync(token, entry, page_id, props):
            with _rate_lock:
                elapsed = time.monotonic() - _last_request[0]
                if elapsed < 0.35:
                    time.sleep(0.35 - elapsed)
                _last_request[0] = time.monotonic()
            return sync_archive_entry(token, entry, page_id, props)

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(_rate_limited_sync, token, entry, page_id, props): entry
                for entry, page_id, props in sync_items
            }
            for future in concurrent.futures.as_completed(future_map):
                entry = future_map[future]
                try:
                    notion_page_id = future.result()
                except Exception as exc:
                    print(f"Failed syncing {entry.get('title', entry.get('original_path', 'entry'))}: {exc}", file=sys.stderr)
                    failures += 1
                    continue
                entry["notion_page_id"] = notion_page_id
                entry["notion_url"] = f"https://www.notion.so/{notion_page_id.replace('-', '')}"
                entry["synced_at"] = datetime.now().isoformat(timespec="seconds")
                synced += 1

    if synced:
        write_manifest(manifest_path, entries)
        print(f"Synced {synced} Stonewall Archive entries and updated manifest -> {manifest_path}")
    else:
        print(f"Synced {synced} Stonewall Archive entries; manifest not updated (no successful syncs) -> {manifest_path}")
    if failures:
        print(f"Encountered {failures} sync failures.", file=sys.stderr)
        return 1
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    review_queue_path = Path(args.review_queue)
    output_path = Path(args.output)

    entries = load_manifest(manifest_path)
    total = len(entries)
    synced = sum(1 for entry in entries if entry.get("notion_page_id"))
    unsynced = total - synced

    case_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    extension_counts: dict[str, int] = {}
    for entry in entries:
        case_key = entry.get("primary_case_tag") or "unmatched"
        case_counts[case_key] = case_counts.get(case_key, 0) + 1
        status = entry.get("case_match_status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        ext = entry.get("extension", "unknown")
        extension_counts[ext] = extension_counts.get(ext, 0) + 1

    unsynced_rows = [
        (
            entry.get("primary_case_tag") or "unmatched",
            entry.get("title") or Path(entry.get("original_path", "")).name or "(untitled)",
            entry.get("extraction_status", "unknown"),
            entry.get("case_match_status", "unknown"),
            entry.get("derivative_path", ""),
        )
        for entry in entries
        if not entry.get("notion_page_id")
    ]

    review_summary = ""
    if review_queue_path.exists():
        lines = review_queue_path.read_text(encoding="utf-8").splitlines()
        review_summary = "\n".join(lines[:24]).strip()

    def render_kv_table(title: str, data: dict[str, int]) -> list[str]:
        if not data:
            return [f"## {title}", "", "_No rows._", ""]
        lines = [f"## {title}", "", "| Key | Count |", "| --- | ---: |"]
        for key, value in sorted(data.items(), key=lambda item: (-item[1], item[0].lower())):
            lines.append(f"| {key} | {value} |")
        lines.append("")
        return lines

    lines: list[str] = [
        "# OneDrive Intake + Notion Sync Status Report",
        "",
        f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC",
        "",
        "## Executive Summary",
        "",
        f"- Manifest path: `{manifest_path}`",
        f"- Total intake rows: **{total}**",
        f"- Synced to Notion: **{synced}**",
        f"- Pending Notion sync: **{unsynced}**",
        "",
    ]
    lines.extend(render_kv_table("Case Distribution", case_counts))
    lines.extend(render_kv_table("Case Match Status Distribution", status_counts))
    lines.extend(render_kv_table("Extension Distribution", extension_counts))

    lines.extend(
        [
            "## Pending Notion Upserts",
            "",
            "| Case | Title | Extraction | Match Status | Derivative Path |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    if unsynced_rows:
        for case_tag, title, extraction_status, match_status, derivative_path in unsynced_rows:
            lines.append(
                f"| {case_tag} | {title} | {extraction_status} | {match_status} | `{derivative_path}` |"
            )
    else:
        lines.append("| _None_ |  |  |  |  |")
    lines.append("")

    lines.extend(["## Review Queue Snapshot", ""])
    if review_summary:
        lines.extend(["```markdown", review_summary, "```", ""])
    else:
        lines.extend(["_Review queue file not found or empty._", ""])

    lines.extend(
        [
            "## Suggested Next Commands",
            "",
            "```bash",
            "python3 scripts/ingest_onedrive.py refresh-cases",
            "python3 scripts/ingest_onedrive.py ingest --root all --limit 200",
            "python3 scripts/ingest_onedrive.py sync-notion --only-unsynced --limit 200 --workers 8",
            "```",
            "",
        ]
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote report -> {output_path}")
    return 0


def sync_archive_entry(token: str, entry: dict, page_id: str | None, props: dict) -> str:
    if page_id:
        notion_api(token, "PATCH", f"pages/{page_id}", {"properties": props})
        return page_id

    created = notion_api(
        token,
        "POST",
        "pages",
        {
            "parent": {"type": "data_source_id", "data_source_id": STONEWALL_ARCHIVE_DS_ID},
            "properties": props,
        },
    )
    created_id = created["id"]
    try:
        append_archive_content(token, created_id, entry)
    except Exception:
        # Roll back the partially created page to avoid leaving an incomplete
        # archive entry that future sync runs will never repair.
        try:
            notion_api(token, "PATCH", f"pages/{created_id}", {"archived": True})
        except Exception:
            # If rollback fails, we still want to surface the original error.
            pass
        raise
    return created_id


def collect_input_files(
    explicit_inputs: list[str] | None,
    root_mode: str,
    globs: list[str] | None,
    extensions: set[str],
    since_dt: datetime | None,
    limit: int,
) -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()
    inputs = [Path(item) for item in explicit_inputs] if explicit_inputs else []
    if not inputs:
        if root_mode in {"all", "personal"}:
            inputs.append(DEFAULT_PERSONAL_ROOT)
        if root_mode in {"all", "firm"}:
            inputs.append(DEFAULT_FIRM_ROOT)

    for input_path in inputs:
        if not input_path.exists():
            continue
        files = [input_path] if input_path.is_file() else (path for path in input_path.rglob("*") if path.is_file())
        for file_path in files:
            suffix = file_path.suffix.lower()
            if suffix not in extensions:
                continue
            if globs and not any(match_glob(file_path, pattern) for pattern in globs):
                continue
            if since_dt and datetime.fromtimestamp(file_path.stat().st_mtime) < since_dt:
                continue
            key = str(file_path.resolve())
            if key in seen:
                continue
            seen.add(key)
            candidates.append(file_path)
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    if limit:
        return candidates[:limit]
    return candidates


def match_glob(path: Path, pattern: str) -> bool:
    regex = re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".")
    return re.search(regex, str(path), flags=re.IGNORECASE) is not None


def parse_since(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise IntakeError("--since must be YYYY-MM-DD") from exc


def load_case_records(path: Path) -> list[CaseRecord]:
    if not path.exists():
        raise IntakeError(f"Case index not found at {path}. Run refresh-cases first or point --case-index elsewhere.")

    raw = json.loads(path.read_text(encoding="utf-8"))
    records: list[CaseRecord] = []
    for item in raw:
        name = item.get("name", "").strip()
        if not name:
            continue
        case_tag = derive_case_tag(name)
        records.append(
            CaseRecord(
                id=item.get("id", ""),
                name=name,
                claim=item.get("claim", "").strip(),
                case_number=item.get("case_number", "").strip(),
                plaintiff=item.get("plaintiff", "").strip(),
                carrier_driver=item.get("carrier_driver", "").strip(),
                legal_hold_status=item.get("legal_hold_status", "").strip(),
                date_of_loss=item.get("date_of_loss", "").strip(),
                date_of_complaint=item.get("date_of_complaint", "").strip(),
                case_tag=case_tag,
                keywords=build_case_keywords(name, item.get("plaintiff", ""), item.get("carrier_driver", ""), case_tag),
                compact_claim=compact_token(item.get("claim", "")),
                compact_case_number=compact_token(item.get("case_number", "")),
            )
        )
    return records


def build_case_keywords(name: str, plaintiff: str, carrier_driver: str, case_tag: str) -> set[str]:
    keywords: set[str] = set()
    base = plaintiff or name.split(" v.")[0]
    for part in re.split(r"[\\/,&]", base):
        keywords.update(tokenize(part))
    keywords.update(tokenize(case_tag))
    keywords.update(tokenize(carrier_driver))
    rhs = name.split(" v.", 1)[1] if " v." in name else ""
    if rhs:
        for part in rhs.split("&"):
            for token in tokenize(part):
                if token not in {"inc", "llc", "co", "corp", "company", "logistics", "transport", "trucking"}:
                    keywords.add(token)
    return {token for token in keywords if len(token) > 2}


def build_ingest_entry(
    source_path: Path,
    derivative_root: Path,
    case_records: list[CaseRecord],
    case_records_by_name: dict[str, CaseRecord],
    manual_override: dict | None,
) -> dict:
    source_root_name, source_root_path, relative_source = identify_source_root(source_path)
    derivative_path = build_derivative_path(derivative_root, source_root_name, relative_source)
    stat = source_path.stat()
    file_sha = sha256_file(source_path)
    extract_result = extract_text(source_path)
    candidates = score_case_matches(source_path, extract_result["text"], case_records)
    primary = choose_primary_case(candidates)
    override_mode = ""
    override_reason = ""
    if manual_override:
        primary, candidates, override_mode, override_reason = apply_manual_override(
            manual_override,
            source_path,
            primary,
            candidates,
            case_records_by_name,
        )
    category, tags = classify_artifact(source_path, extract_result["text"])
    inferred_date = infer_date(source_path)

    return {
        "title": source_path.name,
        "source_root": source_root_name,
        "source_root_path": str(source_root_path) if source_root_path else "",
        "relative_source_path": relative_source.as_posix(),
        "original_path": str(source_path),
        "derivative_path": str(derivative_path),
        "extension": source_path.suffix.lower(),
        "size_bytes": stat.st_size,
        "size_human": human_size(stat.st_size),
        "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "sha256": file_sha,
        "extraction_status": extract_result["status"],
        "extraction_method": extract_result["method"],
        "extraction_error": extract_result.get("error", ""),
        "extracted_chars": len(extract_result["text"]),
        "category": category,
        "tags": tags,
        "date": inferred_date,
        "case_candidates": [candidate.to_dict() for candidate in candidates],
        "primary_case_id": primary.case_id if primary else "",
        "primary_case_name": primary.case_name if primary else "",
        "primary_case_tag": primary.case_tag if primary else "",
        "case_match_score": primary.score if primary else 0,
        "case_match_reasons": primary.reasons if primary else [],
        "case_match_status": case_match_status(candidates, primary, override_mode),
        "legal_hold_status": primary.legal_hold_status if primary else "",
        "date_of_loss": primary.date_of_loss if primary else "",
        "date_of_complaint": primary.date_of_complaint if primary else "",
        "manual_override_mode": override_mode,
        "manual_override_reason": override_reason,
        "notion_page_id": "",
        "notion_url": "",
        "synced_at": "",
        "markdown": render_derivative_markdown(
            source_path, relative_source, extract_result, category, tags, inferred_date, file_sha,
            human_size(stat.st_size), candidates, primary, override_mode, override_reason,
        ),
    }


def identify_source_root(path: Path) -> tuple[str, Path | None, Path]:
    resolved = path.resolve()
    for name, root in (("personal", DEFAULT_PERSONAL_ROOT), ("firm", DEFAULT_FIRM_ROOT)):
        try:
            return name, root, resolved.relative_to(root)
        except ValueError:
            continue
    return "external", None, Path(path.name)


def build_derivative_path(derivative_root: Path, source_root_name: str, relative_source: Path) -> Path:
    target = derivative_root / source_root_name / relative_source
    suffix = relative_source.suffix or ".bin"
    target = target.with_name(f"{relative_source.stem}{suffix}.md")
    if len(str(target)) <= 240:
        return target
    digest = hashlib.sha1(relative_source.as_posix().encode("utf-8")).hexdigest()[:10]
    shortened_name = f"{relative_source.stem[:80]}__{digest}{suffix}.md"
    return derivative_root / source_root_name / relative_source.parent / shortened_name


def extract_text(path: Path) -> dict:
    suffix = path.suffix.lower()
    try:
        if suffix in TEXT_EXTENSIONS:
            text = extract_plain_text(path)
            method = "text"
        elif suffix == ".docx":
            text = extract_docx_text(path)
            method = "docx-xml"
        elif suffix == ".xlsx":
            text = extract_xlsx_text(path)
            method = "xlsx-xml"
        elif suffix == ".pdf":
            text = extract_pdf_text(path)
            method = "pypdf"
        elif suffix == ".eml":
            text = extract_eml_text(path)
            method = "email-parser"
        elif suffix == ".msg":
            text = extract_msg_text(path)
            method = "extract-msg"
        elif suffix == ".zip":
            text = extract_zip_listing(path)
            method = "zip-listing"
        else:
            raise ExtractionUnavailable(f"Unsupported extension {suffix}")
        return {"status": "success", "method": method, "text": normalize_text(text)}
    except ExtractionUnavailable as exc:
        return {"status": "stub", "method": "metadata-only", "text": "", "error": str(exc)}
    except Exception as exc:  # pragma: no cover
        return {"status": "error", "method": "metadata-only", "text": "", "error": str(exc)}


def extract_plain_text(path: Path) -> str:
    raw = path.read_bytes()
    if path.suffix.lower() in {".htm", ".html"}:
        return strip_html(raw.decode("utf-8", errors="ignore"))
    if path.suffix.lower() == ".rtf":
        return strip_rtf(raw.decode("utf-8", errors="ignore"))
    return raw.decode("utf-8", errors="ignore")


def extract_docx_text(path: Path) -> str:
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        try:
            root = ET.fromstring(archive.read("word/document.xml"))
        except KeyError as exc:
            raise ExtractionUnavailable("DOCX file is missing word/document.xml") from exc

    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        parts: list[str] = []
        for node in paragraph.iter():
            tag = node.tag.rsplit("}", 1)[-1]
            if tag == "t" and node.text:
                parts.append(node.text)
            elif tag == "tab":
                parts.append("\t")
            elif tag in {"br", "cr"}:
                parts.append("\n")
        value = "".join(parts).strip()
        if value:
            paragraphs.append(value)
    return "\n\n".join(paragraphs)


def extract_xlsx_text(path: Path) -> str:
    ns = {
        "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    }
    with zipfile.ZipFile(path) as archive:
        shared_strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared_strings = ["".join(node.itertext()) for node in shared_root.findall(".//main:si", ns)]

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rel_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rel_root.findall(".//rel:Relationship", ns)}
        output_parts: list[str] = []
        for sheet in workbook.findall(".//main:sheet", ns):
            sheet_name = sheet.attrib.get("name", "Sheet")
            rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            target = rel_map.get(rel_id, "")
            sheet_path = f"xl/{target}" if not target.startswith("xl/") else target
            if sheet_path not in archive.namelist():
                continue
            sheet_root = ET.fromstring(archive.read(sheet_path))
            rows = [f"## Sheet: {sheet_name}", ""]
            for row in sheet_root.findall(".//main:sheetData/main:row", ns):
                values: list[str] = []
                for cell in row.findall("main:c", ns):
                    cell_type = cell.attrib.get("t", "")
                    value_node = cell.find("main:v", ns)
                    inline_node = cell.find("main:is", ns)
                    value = ""
                    if cell_type == "s" and value_node is not None and value_node.text:
                        index = int(value_node.text)
                        value = shared_strings[index] if index < len(shared_strings) else ""
                    elif cell_type == "inlineStr" and inline_node is not None:
                        value = "".join(inline_node.itertext())
                    elif value_node is not None and value_node.text:
                        value = value_node.text
                    values.append(value.strip())
                if any(values):
                    rows.append("\t".join(values))
            output_parts.append("\n".join(rows).strip())
        return "\n\n".join(output_parts)


def extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise ExtractionUnavailable("PDF extraction needs pypdf. Re-run with `uv run --with pypdf ...`.") from exc

    try:
        reader = PdfReader(str(path), strict=False)
        parts: list[str] = []
        for index, page in enumerate(reader.pages, start=1):
            page_text = normalize_text(page.extract_text() or "")
            if page_text:
                parts.append(f"## Page {index}\n\n{page_text}")
    except Exception as exc:  # pragma: no cover - depends on PDF internals
        if "cryptography" in str(exc).lower():
            raise ExtractionUnavailable(
                "Encrypted PDF needs cryptography. Re-run with `uv run --with pypdf --with cryptography ...`."
            ) from exc
        raise
    if not parts:
        raise ExtractionUnavailable("PDF text extraction returned no text; likely scanned or image-only.")
    return "\n\n".join(parts)


def extract_eml_text(path: Path) -> str:
    with path.open("rb") as handle:
        message = BytesParser(policy=policy.default).parse(handle)
    parts = [
        f"Subject: {message.get('subject', '')}",
        f"From: {message.get('from', '')}",
        f"To: {message.get('to', '')}",
        f"CC: {message.get('cc', '')}",
        "",
    ]
    body = message.get_body(preferencelist=("plain", "html"))
    if body is not None:
        payload = body.get_content()
        parts.append(strip_html(payload) if body.get_content_type() == "text/html" else payload)
    return "\n".join(parts)


def extract_msg_text(path: Path) -> str:
    try:
        import extract_msg  # type: ignore
    except ImportError as exc:
        raise ExtractionUnavailable("MSG extraction needs extract-msg. Re-run with `uv run --with extract-msg ...`.") from exc

    message = extract_msg.Message(str(path))
    return "\n".join(
        [
            f"Subject: {message.subject or ''}",
            f"From: {message.sender or ''}",
            f"To: {message.to or ''}",
            "",
            message.body or "",
        ]
    )


def extract_zip_listing(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        names = sorted(archive.namelist())
    if not names:
        raise ExtractionUnavailable("ZIP file is empty.")
    return "\n".join(names)


def score_case_matches(path: Path, extracted_text: str, case_records: list[CaseRecord]) -> list[MatchCandidate]:
    path_text = str(path).lower()
    text = extracted_text.lower()
    combined_text = f"{path_text}\n{text}"
    compact = compact_token(combined_text)
    path_tokens = tokenize(path_text)
    text_tokens = tokenize(text)
    has_context = any(marker in combined_text for marker in CASE_CONTEXT_MARKERS)
    candidates: list[MatchCandidate] = []

    for case in case_records:
        score = 0
        reasons: list[str] = []
        path_hits = 0
        text_hits = 0
        if case.compact_claim and case.compact_claim in compact:
            score += 120
            reasons.append(f"claim:{case.claim}")
        if case.compact_case_number and case.compact_case_number in compact:
            score += 100
            reasons.append(f"case-number:{case.case_number}")

        case_tag_tokens = tokenize(case.case_tag)
        if case_tag_tokens and case_tag_tokens.issubset(path_tokens):
            score += 40
            reasons.append(f"path-tag:{case.case_tag}")
        elif case_tag_tokens and case_tag_tokens.issubset(text_tokens):
            score += 28
            reasons.append(f"text-tag:{case.case_tag}")

        for keyword in case.keywords:
            if keyword in AMBIGUOUS_KEYWORDS and not has_context:
                continue
            if keyword in path_tokens:
                score += 20
                path_hits += 1
                reasons.append(f"path-keyword:{keyword}")
            elif keyword in text_tokens:
                score += 8
                text_hits += 1
                reasons.append(f"text-keyword:{keyword}")

        if path_hits >= 2:
            score += 25
            reasons.append("path-keyword-cluster")
        if text_hits >= 3:
            score += 15
            reasons.append("text-keyword-cluster")

        if score <= 0:
            continue

        deduped = []
        for reason in reasons:
            if reason not in deduped:
                deduped.append(reason)

        candidates.append(
            MatchCandidate(
                case_id=case.id,
                case_name=case.name,
                case_tag=case.case_tag,
                score=score,
                reasons=deduped[:8],
                claim=case.claim,
                case_number=case.case_number,
                legal_hold_status=case.legal_hold_status,
                date_of_loss=case.date_of_loss,
                date_of_complaint=case.date_of_complaint,
            )
        )

    candidates.sort(key=lambda item: (-item.score, item.case_name.lower()))
    return candidates[:5]


def choose_primary_case(candidates: list[MatchCandidate]) -> MatchCandidate | None:
    if not candidates:
        return None
    best = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    best_has_path_tag = any(reason.startswith("path-tag:") for reason in best.reasons)
    second_has_path_tag = any(reason.startswith("path-tag:") for reason in second.reasons) if second else False
    best_has_tag_signal = any(reason.startswith(("path-tag:", "text-tag:")) for reason in best.reasons)
    if best.score >= 100:
        return best
    if best.score >= 60 and (second is None or best.score - second.score >= 15):
        return best
    if best.score >= 60 and best_has_path_tag and not second_has_path_tag:
        return best
    if best.score >= 36 and best_has_tag_signal and (second is None or best.score - second.score >= 20):
        return best
    return None


def parse_manual_overrides_file(filepath: Path) -> dict[str, dict]:
    """Parse a manual overrides JSON file (list or dict format) into a dict
    keyed by original_path."""
    raw = json.loads(filepath.read_text(encoding="utf-8"))
    overrides: dict[str, dict] = {}
    if isinstance(raw, list):
        for item in raw:
            original_path = str(item.get("original_path", "")).strip()
            if original_path:
                overrides[original_path] = item
    elif isinstance(raw, dict):
        for original_path, item in raw.items():
            if isinstance(item, dict):
                merged = dict(item)
                merged.setdefault("original_path", original_path)
                overrides[str(original_path)] = merged
    return overrides


def load_manual_overrides(path: Path) -> dict[str, dict]:
    if not path.exists():
        if path == DEFAULT_MANUAL_OVERRIDES and LEGACY_MANUAL_OVERRIDES.exists():
            print(
                f"Manual overrides: local file not found, falling back to {LEGACY_MANUAL_OVERRIDES}",
                file=sys.stderr,
            )
            try:
                return parse_manual_overrides_file(LEGACY_MANUAL_OVERRIDES)
            except (json.JSONDecodeError, OSError) as exc:
                print(f"Manual overrides: skipping legacy fallback — could not read {LEGACY_MANUAL_OVERRIDES}: {exc}", file=sys.stderr)
                return {}
        return {}
    try:
        overrides = parse_manual_overrides_file(path)
    except (json.JSONDecodeError, OSError) as exc:
        print(
            f"Manual overrides: skipping primary file — could not read {path}: {exc}",
            file=sys.stderr,
        )
        if path == DEFAULT_MANUAL_OVERRIDES and LEGACY_MANUAL_OVERRIDES.exists():
            print(f"Manual overrides: falling back to {LEGACY_MANUAL_OVERRIDES}", file=sys.stderr)
            try:
                return parse_manual_overrides_file(LEGACY_MANUAL_OVERRIDES)
            except (json.JSONDecodeError, OSError) as legacy_exc:
                print(f"Manual overrides: skipping legacy fallback — could not read {LEGACY_MANUAL_OVERRIDES}: {legacy_exc}", file=sys.stderr)
        return {}
    if path == DEFAULT_MANUAL_OVERRIDES and LEGACY_MANUAL_OVERRIDES.exists():
        try:
            legacy_overrides = parse_manual_overrides_file(LEGACY_MANUAL_OVERRIDES)
            for original_path, item in legacy_overrides.items():
                overrides.setdefault(original_path, item)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Manual overrides: skipping legacy merge — could not read {LEGACY_MANUAL_OVERRIDES}: {exc}", file=sys.stderr)
    return overrides


def manual_override_state_changed(existing_entry: dict, manual_override: dict | None) -> bool:
    return manifest_override_signature(existing_entry) != manual_override_signature(manual_override)


def manifest_override_signature(entry: dict) -> tuple[str, str, str]:
    mode = str(entry.get("manual_override_mode", "")).strip().lower()
    reason = str(entry.get("manual_override_reason", "")).strip()
    case_name = str(entry.get("primary_case_name", "")).strip() if mode == "link" else ""
    return mode, reason, case_name


def manual_override_signature(manual_override: dict | None) -> tuple[str, str, str]:
    if not isinstance(manual_override, dict):
        return "", "", ""
    mode = str(manual_override.get("mode", "")).strip().lower()
    reason = str(manual_override.get("reason", "")).strip()
    case_name = str(manual_override.get("case_name", "")).strip() if mode == "link" else ""
    return mode, reason, case_name


def apply_manual_override(
    manual_override: dict,
    source_path: Path,
    primary: MatchCandidate | None,
    candidates: list[MatchCandidate],
    case_records_by_name: dict[str, CaseRecord],
) -> tuple[MatchCandidate | None, list[MatchCandidate], str, str]:
    mode = str(manual_override.get("mode", "")).strip().lower()
    reason = str(manual_override.get("reason", "")).strip()
    if mode == "no_case":
        return None, candidates, "no_case", reason
    if mode == "link":
        case_name = str(manual_override.get("case_name", "")).strip()
        record = case_records_by_name.get(case_name)
        if not record:
            raise IntakeError(f"Manual override for {source_path} references unknown case '{case_name}'.")
        candidate = MatchCandidate(
            case_id=record.id,
            case_name=record.name,
            case_tag=record.case_tag,
            score=999,
            reasons=[f"manual-override:{reason or 'linked by operator'}"],
            claim=record.claim,
            case_number=record.case_number,
            legal_hold_status=record.legal_hold_status,
            date_of_loss=record.date_of_loss,
            date_of_complaint=record.date_of_complaint,
        )
        return candidate, [candidate], "link", reason
    return primary, candidates, "", reason


def case_match_status(candidates: list[MatchCandidate], primary: MatchCandidate | None, override_mode: str = "") -> str:
    if override_mode == "no_case":
        return "resolved-no-case"
    if primary:
        return "linked"
    if candidates and candidates[0].score >= 20:
        return "review"
    return "unmatched"


def classify_artifact(path: Path, extracted_text: str) -> tuple[str, list[str]]:
    path_text = str(path).lower()
    extracted_lower = extracted_text.lower()
    suffix = path.suffix.lower()
    tags: set[str] = set()

    if any(word in path_text or word in extracted_lower for word in ("billing", "prebill", "timesheet", "collections", "invoice", "ledes")):
        tags.update({"billing", "forensics"})
        return "Billing Forensics", sorted(tags)
    if suffix in {".csv", ".xlsx"} and any(
        word in path_text or word in extracted_lower
        for word in ("delivery", "driver", "orion", "telematics", "pmi", "repair", "maintenance", "gps")
    ):
        tags.update({"discovery", "forensics"})
        return "Case Record", sorted(tags)
    if "otter" in path_text:
        tags.update({"otter", "verbatim"})
        return "Otter.ai Call", sorted(tags)
    if any(word in path_text for word in ("depo", "deposition")):
        tags.update({"depo", "verbatim"})
        return "Deposition Transcript", sorted(tags)
    if "teams" in path_text:
        tags.add("teams")
        if suffix in {".pdf", ".png", ".jpg", ".jpeg"}:
            tags.add("screenshot")
            return "Workflow Evidence", sorted(tags)
        return "Teams Archive", sorted(tags)
    if any(word in path_text for word in ("chapter", "book", "notes_from", "notes from")):
        tags.add("narrative")
        return "Chapter", sorted(tags)
    if any(word in path_text for word in ("transcript", "verbatim")):
        tags.add("verbatim")
        return "Verbatim Transcription", sorted(tags)
    if any(word in path_text for word in ("motion", "notice", "order", "proposal", "response", "rog", "rtp", "rfa", "subpoena", "complaint", "cmo", "hearing")):
        tags.add("discovery")
        return "Case Record", sorted(tags)
    if any(word in extracted_text.lower() for word in ("teams", "chat", "message")) and suffix in {".pdf", ".png", ".jpg", ".jpeg"}:
        tags.update({"teams", "screenshot"})
        return "Workflow Evidence", sorted(tags)
    return "Misc Evidence", sorted(tags)


def render_derivative_markdown(
    source_path: Path,
    relative_source: Path,
    extract_result: dict,
    category: str,
    tags: list[str],
    inferred_date: str,
    sha256_value: str,
    size_human: str,
    case_candidates: list[MatchCandidate],
    primary_case: MatchCandidate | None,
    override_mode: str,
    override_reason: str,
) -> str:
    lines = [
        "---",
        f'title: "{escape_yaml(source_path.name)}"',
        f'original_path: "{escape_yaml(str(source_path))}"',
        f'relative_source_path: "{escape_yaml(relative_source.as_posix())}"',
        f'sha256: "{sha256_value}"',
        f'extraction_status: "{extract_result["status"]}"',
        f'extraction_method: "{extract_result["method"]}"',
        f'category: "{category}"',
        f'date: "{inferred_date}"' if inferred_date else 'date: ""',
        f'size: "{size_human}"',
        f'tags: {json.dumps(tags)}',
        f'primary_case: "{escape_yaml(primary_case.case_name if primary_case else "")}"',
        f'legal_hold_status: "{escape_yaml(primary_case.legal_hold_status if primary_case else "")}"',
        f'date_of_loss: "{escape_yaml(primary_case.date_of_loss if primary_case else "")}"',
        f'date_of_complaint: "{escape_yaml(primary_case.date_of_complaint if primary_case else "")}"',
        "---",
        "",
        f"# {source_path.name}",
        "",
        "## Source Metadata",
        f"- Original path: `{source_path}`",
        f"- Relative source path: `{relative_source.as_posix()}`",
        f"- SHA256: `{sha256_value}`",
        f"- Extraction: `{extract_result['status']}` via `{extract_result['method']}`",
    ]
    if inferred_date:
        lines.append(f"- Inferred date: `{inferred_date}`")
    if primary_case:
        lines.extend(
            [
                f"- Primary case: `{primary_case.case_name}` (score {primary_case.score})",
                f"- Legal hold status: `{primary_case.legal_hold_status or 'Unknown'}`",
                f"- Date of loss: `{primary_case.date_of_loss or 'Unknown'}`",
                f"- Date of complaint: `{primary_case.date_of_complaint or 'Unknown'}`",
            ]
        )
    elif override_mode == "no_case":
        message = "manual override: no single primary case"
        if override_reason:
            message += f" ({override_reason})"
        lines.append(f"- Primary case: {message}")
    elif case_candidates:
        lines.append("- Primary case: review required")
    else:
        lines.append("- Primary case: no match")
    if extract_result.get("error"):
        lines.append(f"- Extraction note: `{extract_result['error']}`")

    lines.extend(["", "## Case Candidates"])
    if case_candidates:
        for candidate in case_candidates:
            lines.append(f"- `{candidate.case_name}` ({candidate.score}) — {', '.join(candidate.reasons)}")
    else:
        lines.append("- None")

    lines.extend(["", "## Extracted Text", "", extract_result["text"] or "_No extracted text available in this run._"])
    return "\n".join(lines).strip() + "\n"


def write_derivative(entry: dict) -> None:
    derivative_path = Path(entry["derivative_path"])
    derivative_path.parent.mkdir(parents=True, exist_ok=True)
    derivative_path.write_text(entry["markdown"], encoding="utf-8")


def format_preview(entry: dict) -> str:
    primary = entry["primary_case_name"] or "no auto-link"
    note = f" | {entry['extraction_error']}" if entry.get("extraction_error") else ""
    return f"[DRY RUN] {entry['title']} -> {entry['derivative_path']} | {entry['category']} | {primary} | {entry['extraction_status']}/{entry['extraction_method']}{note}"


def load_manifest(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_manifest(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(strip_markdown_blob(entry), ensure_ascii=False) for entry in entries)
    path.write_text(payload + ("\n" if payload else ""), encoding="utf-8")


def strip_markdown_blob(entry: dict) -> dict:
    clean = dict(entry)
    clean.pop("markdown", None)
    return clean


def write_review_queue(path: Path, entries: list[dict]) -> None:
    review_entries = [entry for entry in entries if entry.get("case_match_status") in {"review", "unmatched"}]
    lines = [
        "# OneDrive Intake Review Queue",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "| Status | Title | Top Candidates | Original Path |",
        "|---|---|---|---|",
    ]
    for entry in review_entries:
        candidates = entry.get("case_candidates", [])
        candidate_text = "; ".join(f"{item['case_name']} ({item['score']})" for item in candidates[:3]) if candidates else "None"
        lines.append(f"| {entry.get('case_match_status', 'unmatched')} | {escape_pipe(entry['title'])} | {escape_pipe(candidate_text)} | `{entry['original_path']}` |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_sync_plan(path: Path, sync_items: list[tuple[dict, str | None, dict]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for entry, page_id, props in sync_items:
            source_root = entry.get("source_root", "")
            orig = normalize_path_for_export(entry.get("original_path", ""), source_root)
            deriv = normalize_path_for_export(entry.get("derivative_path", ""), source_root)
            row = {
                "action": "update" if page_id else "create",
                "title": entry.get("title", ""),
                "original_path": orig,
                "derivative_path": deriv,
                "existing_page_id": page_id or "",
                "target_data_source_id": STONEWALL_ARCHIVE_DS_ID,
                "properties": props,
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def fetch_archive_pages_by_file_path(token: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for page in notion_paginate_data_source(token, STONEWALL_ARCHIVE_DS_ID):
        file_path = get_notion_text(page.get("properties", {}), "File Path")
        if file_path:
            mapping[file_path] = page["id"]
    return mapping


def build_archive_properties(entry: dict) -> dict:
    source_root = entry.get("source_root", "")
    orig_path = normalize_path_for_export(entry.get("original_path", ""), source_root)
    deriv_path = normalize_path_for_export(entry.get("derivative_path", ""), source_root)
    description = (
        f"Imported from {source_root} OneDrive. Original path: {orig_path}. "
        f"Extraction: {entry['extraction_status']} via {entry['extraction_method']}."
    )[:1800]
    props = {
        "Document": {"title": [{"type": "text", "text": {"content": entry["title"][:2000]}}]},
        "File Path": rich_text_property(deriv_path),
        "Description": rich_text_property(description),
        "Category": {"select": {"name": entry["category"]}},
        "Size": rich_text_property(entry["size_human"]),
        "Status": {"select": {"name": "Active"}},
        "Phase": {"select": {"name": "Root"}},
    }
    if entry.get("date"):
        props["Date"] = {"date": {"start": entry["date"]}}
    allowed_tags = [tag for tag in entry.get("tags", []) if tag in ARCHIVE_TAG_OPTIONS]
    if allowed_tags:
        props["Tags"] = {"multi_select": [{"name": tag} for tag in allowed_tags]}
    case_tag = entry.get("primary_case_tag", "")
    if case_tag in ARCHIVE_CASE_OPTIONS:
        props["Cases"] = {"multi_select": [{"name": case_tag}]}
    if entry.get("primary_case_id"):
        props["⚖️ Case"] = {"relation": [{"id": entry["primary_case_id"]}]}
    return props


def append_archive_content(token: str, page_id: str, entry: dict) -> None:
    excerpt = ""
    derivative_path = Path(entry["derivative_path"])
    if derivative_path.exists():
        excerpt = derivative_path.read_text(encoding="utf-8", errors="ignore").split("## Extracted Text", 1)[-1].strip()[:1500]

    children = [
        notion_paragraph("Source intake metadata"),
        notion_bulleted(f"Original path: {entry['original_path']}"),
        notion_bulleted(f"SHA256: {entry['sha256']}"),
        notion_bulleted(f"Extraction: {entry['extraction_status']} via {entry['extraction_method']}"),
        notion_bulleted(f"Case match: {entry.get('primary_case_name') or 'review required'}"),
    ]
    if excerpt:
        children.append({"object": "block", "type": "code", "code": {"language": "markdown", "rich_text": notion_rich_text(excerpt)}})
    notion_api(token, "PATCH", f"blocks/{page_id}/children", {"children": children})


def notion_paragraph(text: str) -> dict:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": notion_rich_text(text)}}


def notion_bulleted(text: str) -> dict:
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": notion_rich_text(text)}}


def notion_rich_text(text: str) -> list[dict]:
    chunks = []
    remaining = text
    while remaining:
        chunk = remaining[:1800]
        chunks.append({"type": "text", "text": {"content": chunk}})
        remaining = remaining[1800:]
    return chunks or [{"type": "text", "text": {"content": ""}}]


def rich_text_property(text: str) -> dict:
    return {"rich_text": notion_rich_text(text[:1800])}


def notion_paginate_data_source(token: str, data_source_id: str) -> list[dict]:
    results: list[dict] = []
    cursor = None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        response = notion_api(token, "POST", f"data_sources/{data_source_id}/query", body)
        results.extend(response.get("results", []))
        if not response.get("has_more"):
            return results
        cursor = response.get("next_cursor")
        time.sleep(0.35)


def notion_api(token: str, method: str, endpoint: str, data: dict | None = None, retries: int = 4) -> dict:
    url = f"https://api.notion.com/v1/{endpoint}"
    for attempt in range(retries):
        try:
            request = urllib.request.Request(
                url,
                data=json.dumps(data).encode("utf-8") if data is not None else None,
                headers={"Authorization": f"Bearer {token}", "Notion-Version": NOTION_API_VERSION, "Content-Type": "application/json"},
                method=method,
            )
            with urllib.request.urlopen(request) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            if exc.code == 429 and attempt < retries - 1:
                time.sleep(float(exc.headers.get("Retry-After", 1)) + 0.5)
                continue
            raise IntakeError(f"Notion API {exc.code}: {body[:300]}") from exc
        except urllib.error.URLError as exc:
            if attempt < retries - 1:
                time.sleep(1.0)
                continue
            reason = getattr(exc, "reason", exc)
            raise IntakeError(f"Network error contacting Notion API ({endpoint}): {reason}") from exc
    raise IntakeError(f"Failed Notion request after {retries} attempts: {method} {endpoint}")


def get_notion_text(props: dict, name: str) -> str:
    prop = props.get(name, {})
    if prop.get("type") == "title":
        return "".join(item.get("plain_text", "") for item in prop.get("title", []))
    if prop.get("type") == "rich_text":
        return "".join(item.get("plain_text", "") for item in prop.get("rich_text", []))
    if prop.get("type") == "number":
        number = prop.get("number")
        return "" if number is None else str(number)
    return ""


def get_notion_select(props: dict, name: str) -> str:
    select = props.get(name, {}).get("select")
    return select.get("name", "") if select else ""


def get_notion_date(props: dict, name: str) -> str:
    date_value = props.get(name, {}).get("date")
    return date_value.get("start", "") if date_value else ""


def infer_date(path: Path) -> str:
    text = path.name
    for pattern in (
        r"(?P<year>20\d{2})[-_.](?P<month>\d{1,2})[-_.](?P<day>\d{1,2})",
        r"(?P<month>\d{1,2})[._-](?P<day>\d{1,2})[._-](?P<year>\d{2,4})",
    ):
        match = re.search(pattern, text)
        if not match:
            continue
        year = int(match.group("year"))
        if year < 100:
            year += 2000
        try:
            return datetime(year, int(match.group("month")), int(match.group("day"))).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")


def compact_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def tokenize(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 2}


def derive_case_tag(name: str) -> str:
    lhs = re.split(r"\s+v\.?\s+", name, maxsplit=1)[0].strip()
    return re.sub(r"\s*\(.*?\)\s*", "", lhs)


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<br\s*/?>", "\n", text)
    text = re.sub(r"(?s)</p\s*>", "\n\n", text)
    text = re.sub(r"(?s)<.*?>", " ", text)
    return html.unescape(normalize_text(text))


def strip_rtf(text: str) -> str:
    text = re.sub(r"\\par[d]?", "\n", text)
    text = re.sub(r"\\'[0-9a-fA-F]{2}", "", text)
    text = re.sub(r"\\[a-z]+\d* ?", " ", text)
    text = text.replace("{", "").replace("}", "")
    return normalize_text(text)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def human_size(size_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    size = float(size_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size_bytes} B"


def escape_yaml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def escape_pipe(value: str) -> str:
    return value.replace("|", "\\|")


def normalize_path_for_export(path_str: str, source_root: str = "") -> str:
    """Return a repo-relative path string, stripping machine-specific prefixes.

    Derivative paths are anchored at the last occurrence of 'sources/'; original
    paths fall back to 'source_root/filename'.  Forward slashes are always used.
    """
    if not path_str:
        return path_str
    norm = path_str.replace("\\", "/")
    norm = norm[2:] if norm.startswith("./") else norm
    for anchor in ("sources/onedrive_ingest/", "sources/"):
        idx = norm.rfind(anchor)
        if idx >= 0:
            return norm[idx:]
    if source_root:
        filename = norm.rsplit("/", 1)[-1]
        return f"{source_root}/{filename}"
    # No anchor and no source_root — fall back to bare filename to avoid
    # emitting machine-specific absolute paths.
    return norm.rsplit("/", 1)[-1]


if __name__ == "__main__":
    raise SystemExit(main())
