#!/usr/bin/env python3
"""Offline Legal Matters backfill — produces a Notion-ready CSV and markdown
push plan without requiring a live ``NOTION_TOKEN``.

Aggregates case metadata from ``scripts/case_index.json`` and
``scripts/case_dates.json``, optionally enriches with complaint-date
candidates extracted from ``sources/emails/consolidated_emails.json``
and markdown scans, and writes:

* ``catalog/intake/legal_matters_offline_backfill_{stamp}.csv``
* ``catalog/intake/legal_matters_offline_backfill_{stamp}.md``

Usage::

    python scripts/legal_matters_offline_backfill.py --stamp 2026-04-02
"""
from __future__ import annotations

import argparse
import csv
import glob
import io
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_CASE_INDEX = REPO_ROOT / "scripts" / "case_index.json"
DEFAULT_CASE_DATES = REPO_ROOT / "scripts" / "case_dates.json"
DEFAULT_EMAILS = REPO_ROOT / "sources" / "emails" / "consolidated_emails.json"

MAX_SCAN_FILE_BYTES = 512_000

# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

_DATE_PATTERNS = [
    (re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$"), "MDY4"),
    (re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2})$"), "MDY2"),
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})$"), "ISO"),
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})T"), "ISO_T"),
]

EMBEDDED_DATE_RE = re.compile(
    r"(?:^|[^0-9])(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})(?:[^0-9]|$)"
)


def normalize_date(raw: str) -> str | None:
    """Return an ISO ``YYYY-MM-DD`` string or *None* if *raw* is
    unparseable."""
    text = raw.strip()
    if not text:
        return None
    for pat, kind in _DATE_PATTERNS:
        m = pat.match(text)
        if not m:
            continue
        if kind == "MDY4":
            month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        elif kind == "MDY2":
            month, day, yr2 = int(m.group(1)), int(m.group(2)), int(m.group(3))
            year = 2000 + yr2 if yr2 < 70 else 1900 + yr2
        elif kind in ("ISO", "ISO_T"):
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            continue
        try:
            datetime(year, month, day)
        except ValueError:
            return None
        return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def choose_email_date(candidates: list[str]) -> str | None:
    """Pick the best complaint-date candidate by frequency, breaking ties
    by earliest date."""
    if not candidates:
        return None
    freq: dict[str, int] = {}
    for d in candidates:
        freq[d] = freq.get(d, 0) + 1
    max_count = max(freq.values())
    top = sorted(d for d, c in freq.items() if c == max_count)
    return top[0] if top else None


def _clean_field(value: str) -> str:
    """Collapse embedded newlines/whitespace and truncate at 200 chars."""
    text = re.sub(r"[\r\n]+", " ", value)
    text = re.sub(r"\s{2,}", " ", text).strip()
    if len(text) > 200:
        text = text[:197] + "\u2026"
    return text


# ---------------------------------------------------------------------------
# Candidate extraction
# ---------------------------------------------------------------------------


def extract_email_candidates(
    emails_path: Path,
    cases: dict[str, dict],
) -> dict[str, list[str]]:
    """Scan the consolidated emails file for complaint-date signals."""
    candidates: defaultdict[str, list[str]] = defaultdict(list)
    if not emails_path.exists():
        return dict(candidates)
    try:
        raw = json.loads(emails_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(candidates)
    emails = raw if isinstance(raw, list) else []
    for email_rec in emails:
        body = email_rec.get("body", "") or ""
        subject = email_rec.get("subject", "") or ""
        text = f"{subject} {body}"
        if not re.search(r"complaint", text, re.IGNORECASE):
            continue
        case_name = email_rec.get("case_name") or email_rec.get("matter")
        if not case_name or case_name not in cases:
            continue
        for m in EMBEDDED_DATE_RE.finditer(text):
            iso = normalize_date(m.group(1))
            if iso:
                candidates[case_name].append(iso)
    return dict(candidates)


def scan_markdown_candidates(
    cases: dict[str, dict] | None = None,
    patterns: list[str] | None = None,
) -> dict[str, list[str]]:
    """Scan markdown files for complaint-context date signals.

    Results are keyed by case name (matched from file path) so they can
    be merged directly with email candidates.  Files that don't match any
    known case name are keyed by filepath as a fallback.
    """
    candidates: defaultdict[str, list[str]] = defaultdict(list)
    if patterns is None:
        patterns = [
            str(REPO_ROOT / "sources" / "emails" / "**" / "*.md"),
            str(REPO_ROOT / "catalog" / "**" / "*.md"),
        ]
    case_names = list(cases.keys()) if cases else []
    for pattern in patterns:
        for filepath in glob.iglob(pattern, recursive=True):
            try:
                size = os.path.getsize(filepath)
                if size > MAX_SCAN_FILE_BYTES:
                    continue
                text = Path(filepath).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not re.search(r"complaint", text, re.IGNORECASE):
                continue
            dates: list[str] = []
            for m in EMBEDDED_DATE_RE.finditer(text):
                iso = normalize_date(m.group(1))
                if iso:
                    dates.append(iso)
            if not dates:
                continue
            # Try to map the file to a known case name
            key = filepath
            fp_lower = filepath.lower()
            for name in case_names:
                if name.lower().replace(" ", "_") in fp_lower or name.lower().replace(" ", "-") in fp_lower:
                    key = name
                    break
            candidates[key].extend(dates)
    return dict(candidates)


def merge_candidate_sources(
    *candidate_maps: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Combine multiple candidate maps into a single candidate dictionary."""
    merged: defaultdict[str, list[str]] = defaultdict(list)
    for candidate_map in candidate_maps:
        for name, values in candidate_map.items():
            merged[name].extend(values)
    return dict(merged)


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------


def load_cases(case_index_path: Path) -> dict[str, dict]:
    """Load case records from the case index JSON."""
    if not case_index_path.exists():
        return {}
    try:
        raw = json.loads(case_index_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if isinstance(raw, list):
        result: dict[str, dict] = {}
        for rec in raw:
            name = rec.get("name") or rec.get("case_name") or ""
            if name:
                result[name] = rec
        return result
    if isinstance(raw, dict):
        return raw
    return {}


def load_case_dates(case_dates_path: Path) -> dict[str, dict]:
    """Load supplementary case dates (dict or list form)."""
    if not case_dates_path.exists():
        return {}
    try:
        raw = json.loads(case_dates_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        result: dict[str, dict] = {}
        for rec in raw:
            name = rec.get("name") or rec.get("case_name") or ""
            if name:
                result[name] = rec
        return result
    return {}


def build_rows(
    cases: dict[str, dict],
    case_dates: dict[str, dict],
    complaint_date_candidates: dict[str, list[str]],
) -> list[dict[str, str]]:
    """Build CSV rows for each case."""
    rows: list[dict[str, str]] = []
    for case_name, rec in sorted(cases.items()):
        complaint_date = ""
        source = ""
        dates_rec = case_dates.get(case_name, {})
        if dates_rec.get("complaint_date"):
            complaint_date = dates_rec["complaint_date"]
            source = "case_dates"
        elif rec.get("date_of_complaint"):
            complaint_date = rec["date_of_complaint"]
            source = "case_index"
        elif case_name in complaint_date_candidates:
            chosen = choose_email_date(complaint_date_candidates[case_name])
            if chosen:
                complaint_date = chosen
                source = "emails.complaint_context"

        plaintiff = _clean_field(rec.get("plaintiff", "") or "")
        carrier_driver = _clean_field(rec.get("carrier_driver", "") or "")
        claim_number = rec.get("claim") or rec.get("claim_number") or ""
        dol = dates_rec.get("date_of_loss", "") or rec.get("date_of_loss", "") or ""

        rows.append({
            "case_name": case_name,
            "claim_number": claim_number,
            "plaintiff": plaintiff,
            "carrier_driver": carrier_driver,
            "date_of_loss": dol,
            "complaint_date": complaint_date,
            "complaint_source": source,
        })
    return rows


def write_outputs(
    rows: list[dict[str, str]],
    stamp: str,
    out_dir: Path,
) -> tuple[Path, Path]:
    """Write the CSV and markdown summary."""
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"legal_matters_offline_backfill_{stamp}.csv"
    md_path = out_dir / f"legal_matters_offline_backfill_{stamp}.md"

    fieldnames = [
        "case_name", "claim_number", "plaintiff", "carrier_driver",
        "date_of_loss", "complaint_date", "complaint_source",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    has_complaint = [r for r in rows if r["complaint_date"]]
    buf = io.StringIO()
    buf.write(f"# Legal Matters Offline Backfill\n\n")
    buf.write(f"Generated for stamp: {stamp}\n\n")
    buf.write(f"- Total cases: {len(rows)}\n")
    buf.write(f"- Cases with complaint date recommendation: {len(has_complaint)}\n\n")
    if has_complaint:
        buf.write("## Complaint Date Recommendations\n\n")
        buf.write("| Case | Complaint Date | Source |\n")
        buf.write("|------|---------------|--------|\n")
        for r in has_complaint:
            buf.write(f"| {r['case_name']} | {r['complaint_date']} | {r['complaint_source']} |\n")
    md_path.write_text(buf.getvalue(), encoding="utf-8")
    return csv_path, md_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Legal Matters backfill")
    parser.add_argument(
        "--stamp",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Date stamp for output files (default: today)",
    )
    parser.add_argument("--case-index", default=str(DEFAULT_CASE_INDEX))
    parser.add_argument("--case-dates", default=str(DEFAULT_CASE_DATES))
    parser.add_argument("--emails", default=str(DEFAULT_EMAILS))
    parser.add_argument(
        "--out-dir",
        default=str(REPO_ROOT / "catalog" / "intake"),
    )
    args = parser.parse_args(argv)

    cases = load_cases(Path(args.case_index))
    case_dates = load_case_dates(Path(args.case_dates))
    email_candidates = extract_email_candidates(Path(args.emails), cases)
    markdown_candidates = scan_markdown_candidates(cases)
    all_candidates = merge_candidate_sources(email_candidates, markdown_candidates)
    rows = build_rows(cases, case_dates, all_candidates)
    csv_path, md_path = write_outputs(rows, args.stamp, Path(args.out_dir))

    print(f"Wrote {len(rows)} rows to {csv_path}")
    print(f"Wrote summary to {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
