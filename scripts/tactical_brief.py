#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "catalog" / "manifest.md"
DEFAULT_CASE_DATES = REPO_ROOT / "scripts" / "case_dates.json"
DEFAULT_CASE_MD = REPO_ROOT / "catalog" / "index_by_case.md"
DEFAULT_REPORT = REPO_ROOT / "catalog" / "intake" / "repo_consistency_report.json"

FIELD_RE = re.compile(r"^- \*\*(.+?)\*\*: ?(.*)$")
INDENT_BULLET_RE = re.compile(r"^\s{2}- (.+)$")
DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b")
CASE_SECTION_RE = re.compile(r"^## (.+)$")

GENERIC_CASE_LABELS = {"—", "-", "Multi-Case", "Multiple", "Multiple M&M"}
LOW_SIGNAL_TOKENS = {
    "a", "and", "archive", "attorney", "call", "case", "chain", "claims", "combined",
    "conference", "counsel", "court", "data", "date", "depo", "deposition", "discovery",
    "document", "driver", "email", "emails", "eport", "file", "full", "hearing", "legal",
    "matters", "md", "mediation", "motion", "notes", "other", "pdf", "plaintiff", "prep",
    "record", "report", "screenshot", "sdt", "service", "summary", "team", "teams", "text",
    "the", "to", "transcript", "v",
}
OPEN_LOOP_MARKERS = {
    "tbd", "pending", "demanded", "requested", "unresolved", "needed", "need", "await",
    "follow-up", "follow up", "withheld", "unsigned", "not been", "not yet",
    "or motion to compel", "due", "deadline", "objection",
}


@dataclass(frozen=True)
class ArtifactRow:
    artifact_id: str
    file_field: str
    artifact_type: str
    artifact_date: date | None
    raw_date: str
    characters: str
    patterns: str
    case_field: str
    summary: str
    analyzed: str


@dataclass(frozen=True)
class CaseRecord:
    name: str
    claim: str
    reserve: str
    incurred: str
    depo_date: date | None
    disco_date: date | None
    complaint_filed: date | None
    raw: dict[str, str]


@dataclass
class CaseSection:
    heading: str
    fields: dict[str, str] = field(default_factory=dict)
    lists: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))


@dataclass(frozen=True)
class CaseMatcher:
    heading: str
    display_name: str
    tokens: frozenset[str]
    claims: frozenset[str]
    record: CaseRecord | None


@dataclass(frozen=True)
class DatedItem:
    when: date
    case_heading: str
    display_name: str
    label: str
    source: str


def parse_iso_date(value: str) -> date | None:
    text = value.strip()
    if not text or text in {"—", "-"}:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_us_date(value: str) -> date | None:
    text = value.strip()
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def extract_us_dates(text: str) -> list[date]:
    dates: list[date] = []
    for match in DATE_RE.findall(text):
        parsed = parse_us_date(match)
        if parsed:
            dates.append(parsed)
    return dates


def compact_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def tokenize(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 1 and not token.isdigit() and token not in LOW_SIGNAL_TOKENS
    }


def normalize_claim(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def split_manifest_row(line: str) -> list[str] | None:
    parts = [part.strip() for part in line.strip().strip("|").split("|")]
    if len(parts) < 9:
        return None
    if len(parts) == 9:
        return parts
    return parts[:7] + [" | ".join(parts[7:-1]).strip(), parts[-1]]


def parse_manifest_rows(path: Path) -> list[ArtifactRow]:
    rows: list[ArtifactRow] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.startswith("| A"):
            continue
        cells = split_manifest_row(line)
        if cells is None:
            continue
        rows.append(
            ArtifactRow(
                artifact_id=cells[0],
                file_field=cells[1],
                artifact_type=cells[2],
                artifact_date=parse_iso_date(cells[3]),
                raw_date=cells[3],
                characters=cells[4],
                patterns=cells[5],
                case_field=cells[6],
                summary=cells[7],
                analyzed=cells[8],
            )
        )
    return rows


def parse_case_records(path: Path) -> list[CaseRecord]:
    records: list[CaseRecord] = []
    raw = json.loads(path.read_text(encoding="utf-8"))
    for item in raw:
        records.append(
            CaseRecord(
                name=item.get("name", "").strip(),
                claim=item.get("claim", "").strip(),
                reserve=item.get("reserve", "").strip(),
                incurred=item.get("incurred", "").strip(),
                depo_date=parse_us_date(item.get("depo_date", "").strip()),
                disco_date=parse_us_date(item.get("disco_date", "").strip()),
                complaint_filed=parse_us_date(item.get("complaint_filed", "").strip()),
                raw=item,
            )
        )
    return records


def parse_case_sections(path: Path) -> dict[str, CaseSection]:
    sections: dict[str, CaseSection] = {}
    current: CaseSection | None = None
    current_field: str | None = None
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if match := CASE_SECTION_RE.match(raw_line):
            heading = match.group(1).strip()
            current = CaseSection(heading=heading)
            sections[heading] = current
            current_field = None
            continue
        if current is None:
            continue
        if match := FIELD_RE.match(raw_line):
            field_name = match.group(1).strip()
            field_value = match.group(2).strip()
            current.fields[field_name] = field_value
            current_field = field_name
            continue
        if match := INDENT_BULLET_RE.match(raw_line):
            if current_field:
                current.lists[current_field].append(match.group(1).strip())
            continue
        if not raw_line.strip():
            current_field = None
    return sections


def build_section_descriptor(section: CaseSection) -> str:
    parts = [section.heading]
    for key in ("Style", "Plaintiffs", "Plaintiff", "Defendant(s)", "Carrier Driver"):
        value = section.fields.get(key, "")
        if value:
            parts.append(value)
    return " ".join(parts)


def score_text_match(query: str, tokens: set[str], claims: set[str], raw_name: str) -> int:
    query_text = query.lower()
    query_tokens = tokenize(query_text)
    normalized_query = re.sub(r"[^a-z0-9]", "", query_text)
    score = 0
    if normalized_query and normalized_query in re.sub(r"[^a-z0-9]", "", raw_name.lower()):
        score += 8
    score += len(query_tokens & tokens) * 5
    if normalized_query and normalized_query in claims:
        score += 25
    for token in query_tokens:
        if token in claims:
            score += 25
    return score


def match_case_record_to_section(section: CaseSection, records: list[CaseRecord]) -> CaseRecord | None:
    descriptor = build_section_descriptor(section)
    query_tokens = tokenize(descriptor)
    normalized_query = re.sub(r"[^a-z0-9]", "", descriptor.lower())
    best_score = 0
    best_record: CaseRecord | None = None
    for record in records:
        record_tokens = tokenize(record.name)
        score = len(query_tokens & record_tokens) * 5
        normalized_name = re.sub(r"[^a-z0-9]", "", record.name.lower())
        if normalized_query and (normalized_query in normalized_name or normalized_name in normalized_query):
            score += 10
        if section.heading.lower() in record.name.lower():
            score += 10
        if score > best_score:
            best_score = score
            best_record = record
    return best_record if best_score > 0 else None


def build_case_matchers(sections: dict[str, CaseSection], records: list[CaseRecord]) -> dict[str, CaseMatcher]:
    matchers: dict[str, CaseMatcher] = {}
    for heading, section in sections.items():
        record = match_case_record_to_section(section, records)
        raw_parts = [build_section_descriptor(section)]
        claims: set[str] = set()
        if record:
            raw_parts.append(record.name)
            if record.claim:
                claims.add(normalize_claim(record.claim))
        tokens = tokenize(" ".join(raw_parts))
        display_name = section.fields.get("Style") or (record.name if record else "") or heading.title()
        matchers[heading] = CaseMatcher(
            heading=heading,
            display_name=display_name,
            tokens=frozenset(tokens),
            claims=frozenset(claims),
            record=record,
        )
    return matchers


def resolve_case_heading(query: str, matchers: dict[str, CaseMatcher]) -> str | None:
    best_score = 0
    best_heading: str | None = None
    normalized_query = re.sub(r"[^a-z0-9]", "", query.lower())
    for heading, matcher in matchers.items():
        score = score_text_match(query, set(matcher.tokens), set(matcher.claims), matcher.display_name)
        if normalized_query == re.sub(r"[^a-z0-9]", "", heading.lower()):
            score += 20
        if score > best_score:
            best_score = score
            best_heading = heading
    return best_heading if best_score > 0 else None


def split_case_field(case_field: str) -> list[str]:
    if not case_field or case_field in GENERIC_CASE_LABELS:
        return []
    return [part.strip() for part in case_field.split(",") if part.strip() and part.strip() not in GENERIC_CASE_LABELS]


def artifact_case_headings(artifact: ArtifactRow, matchers: dict[str, CaseMatcher]) -> list[str]:
    headings: list[str] = []
    seen: set[str] = set()
    for label in split_case_field(artifact.case_field):
        heading = resolve_case_heading(label, matchers)
        if heading and heading not in seen:
            headings.append(heading)
            seen.add(heading)
    return headings


def infer_case_for_path(path_text: str, matchers: dict[str, CaseMatcher]) -> tuple[str | None, int]:
    best_heading: str | None = None
    best_score = 0
    for heading, matcher in matchers.items():
        score = score_text_match(path_text, set(matcher.tokens), set(matcher.claims), matcher.display_name)
        if score > best_score:
            best_score = score
            best_heading = heading
    return best_heading, best_score


def load_report(path: Path) -> dict:
    if not path.exists():
        return {"uncataloged_canonical_sources": []}
    return json.loads(path.read_text(encoding="utf-8"))


def build_upcoming_items(
    reference_date: date,
    window_days: int,
    sections: dict[str, CaseSection],
    matchers: dict[str, CaseMatcher],
) -> list[DatedItem]:
    items: list[DatedItem] = []
    cutoff = reference_date + timedelta(days=window_days)

    for heading, matcher in matchers.items():
        if matcher.record:
            for label, value in (
                ("Depo Date", matcher.record.depo_date),
                ("Discovery Date", matcher.record.disco_date),
                ("Complaint Filed", matcher.record.complaint_filed),
            ):
                if value and reference_date <= value <= cutoff:
                    items.append(DatedItem(value, heading, matcher.display_name, label, "case_dates.json"))

    for heading, section in sections.items():
        for field_name, field_value in section.fields.items():
            if not field_value:
                continue
            for when in extract_us_dates(field_value):
                if reference_date <= when <= cutoff:
                    items.append(
                        DatedItem(
                            when,
                            heading,
                            matchers[heading].display_name,
                            f"{field_name}: {compact_whitespace(field_value)}",
                            "index_by_case.md",
                        )
                    )
        for field_name, bullets in section.lists.items():
            for bullet in bullets:
                for when in extract_us_dates(bullet):
                    if reference_date <= when <= cutoff:
                        items.append(
                            DatedItem(
                                when,
                                heading,
                                matchers[heading].display_name,
                                f"{field_name}: {compact_whitespace(bullet)}",
                                "index_by_case.md",
                            )
                        )

    deduped: dict[tuple[date, str, str], DatedItem] = {}
    for item in items:
        deduped.setdefault((item.when, item.case_heading, item.label), item)
    return sorted(deduped.values(), key=lambda item: (item.when, item.display_name, item.label))


def build_recent_heat(
    artifacts: list[ArtifactRow],
    matchers: dict[str, CaseMatcher],
    reference_date: date,
    recent_days: int,
) -> list[tuple[str, int, ArtifactRow]]:
    cutoff = reference_date - timedelta(days=recent_days)
    grouped: dict[str, list[ArtifactRow]] = defaultdict(list)
    for artifact in artifacts:
        if not artifact.artifact_date or artifact.artifact_date < cutoff:
            continue
        for heading in artifact_case_headings(artifact, matchers):
            grouped[heading].append(artifact)

    rows: list[tuple[str, int, ArtifactRow]] = []
    for heading, bucket in grouped.items():
        latest = max(bucket, key=lambda item: (item.artifact_date or date.min, item.artifact_id))
        rows.append((heading, len(bucket), latest))
    return sorted(rows, key=lambda row: (-row[1], -(row[2].artifact_date or date.min).toordinal(), row[0]))


def gather_uncataloged_by_case(report: dict, matchers: dict[str, CaseMatcher], min_score: int = 5) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for path_text in report.get("uncataloged_canonical_sources", []):
        heading, score = infer_case_for_path(path_text, matchers)
        if heading and score >= min_score:
            grouped[heading].append(path_text)
    return {heading: sorted(paths) for heading, paths in grouped.items()}


def find_open_loops(section: CaseSection) -> list[str]:
    loops: list[str] = []
    for field_name in ("Mediation", "Key Discovery", "Key Events"):
        value = section.fields.get(field_name, "")
        if value and any(marker in value.lower() for marker in OPEN_LOOP_MARKERS):
            loops.append(compact_whitespace(value))
        for bullet in section.lists.get(field_name, []):
            lowered = bullet.lower()
            if any(marker in lowered for marker in OPEN_LOOP_MARKERS):
                loops.append(compact_whitespace(bullet))
    deduped: list[str] = []
    seen: set[str] = set()
    for loop in loops:
        if loop not in seen:
            deduped.append(loop)
            seen.add(loop)
    return deduped


def truncate(text: str, width: int = 110) -> str:
    text = compact_whitespace(text)
    if len(text) <= width:
        return text
    return text[: width - 3].rstrip() + "..."


def render_today(
    reference_date: date,
    artifacts: list[ArtifactRow],
    sections: dict[str, CaseSection],
    matchers: dict[str, CaseMatcher],
    report: dict,
    window_days: int,
    recent_days: int,
    limit: int,
) -> str:
    upcoming = build_upcoming_items(reference_date, window_days, sections, matchers)[:limit]
    recent = build_recent_heat(artifacts, matchers, reference_date, recent_days)[:limit]
    uncataloged = gather_uncataloged_by_case(report, matchers)
    backlog_rows = sorted(uncataloged.items(), key=lambda item: (-len(item[1]), item[0]))[:limit]

    lines = ["Stonewall Tactical Brief", f"As of: {reference_date.isoformat()}", "", f"Upcoming ({window_days}d window)"]
    if upcoming:
        for item in upcoming:
            lines.append(f"- {item.when.isoformat()} | {item.case_heading} | {truncate(item.label, 120)}")
    else:
        lines.append("- No upcoming dated items found in the current window.")

    lines.extend(["", f"Recent Case Heat ({recent_days}d lookback)"])
    if recent:
        for heading, count, latest in recent:
            lines.append(f"- {heading} | {count} artifacts | latest {latest.raw_date} {latest.artifact_id} {truncate(latest.summary, 95)}")
    else:
        lines.append("- No recent case-linked artifacts in the current window.")

    lines.extend(["", "Open Intake Backlog"])
    if backlog_rows:
        for heading, paths in backlog_rows:
            lines.append(f"- {heading} | {len(paths)} files | {truncate(paths[0], 110)}")
    else:
        remaining = len(report.get("uncataloged_canonical_sources", []))
        lines.append(f"- No case-confident backlog matches. Remaining uncataloged canonical files: {remaining}.")

    return "\n".join(lines)


def render_case(
    query: str,
    artifacts: list[ArtifactRow],
    sections: dict[str, CaseSection],
    matchers: dict[str, CaseMatcher],
    report: dict,
    reference_date: date,
    recent_limit: int,
) -> str:
    heading = resolve_case_heading(query, matchers)
    if not heading:
        raise ValueError(f"No case match for query: {query}")

    matcher = matchers[heading]
    section = sections[heading]
    open_loops = find_open_loops(section)
    backlog = gather_uncataloged_by_case(report, matchers).get(heading, [])
    upcoming = [
        item for item in build_upcoming_items(reference_date, 120, sections, matchers)
        if item.case_heading == heading and item.when >= reference_date
    ][:5]

    recent_artifacts = [artifact for artifact in artifacts if heading in artifact_case_headings(artifact, matchers)]
    recent_artifacts.sort(key=lambda item: (item.artifact_date or date.min, item.artifact_id), reverse=True)

    lines = [f"Case Brief — {heading}", f"Name: {matcher.display_name}"]
    if matcher.record and matcher.record.claim:
        lines.append(f"Claim: {matcher.record.claim}")
    if matcher.record and (matcher.record.reserve or matcher.record.incurred):
        lines.append(f"Reserve / Incurred: {matcher.record.reserve or '—'} / {matcher.record.incurred or '—'}")

    for field_name in (
        "Case No.", "Plaintiffs", "Plaintiff", "Defendant(s)", "Carrier Driver",
        "OC", "Adjuster", "Mediator", "Mediation", "Projected Trial", "Demand",
    ):
        value = section.fields.get(field_name, "")
        if value:
            lines.append(f"{field_name}: {value}")

    lines.append("")
    lines.append("Priority")
    if open_loops:
        for item in open_loops[:6]:
            lines.append(f"- {truncate(item, 120)}")
    else:
        fallback = section.lists.get("Key Discovery", [])[:4]
        if fallback:
            for item in fallback:
                lines.append(f"- {truncate(item, 120)}")
        else:
            lines.append("- No open-loop heuristics surfaced from the case sheet.")

    lines.append("")
    lines.append("Upcoming")
    if upcoming:
        for item in upcoming:
            lines.append(f"- {item.when.isoformat()} | {truncate(item.label, 120)}")
    else:
        lines.append("- No future dated items detected.")

    lines.append("")
    lines.append("Recent Artifacts")
    if recent_artifacts:
        for artifact in recent_artifacts[:recent_limit]:
            lines.append(f"- {artifact.raw_date or '—'} | {artifact.artifact_id} | {truncate(artifact.summary, 120)}")
    else:
        lines.append("- No manifest artifacts matched this case.")

    lines.append("")
    lines.append("Open Intake")
    if backlog:
        for path_text in backlog[:6]:
            lines.append(f"- {path_text}")
    else:
        lines.append("- No confidently matched uncataloged files in the current verifier report.")

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    common.add_argument("--case-dates", default=str(DEFAULT_CASE_DATES))
    common.add_argument("--case-md", default=str(DEFAULT_CASE_MD))
    common.add_argument("--report", default=str(DEFAULT_REPORT))
    common.add_argument("--date", dest="reference_date", default=date.today().isoformat())

    parser = argparse.ArgumentParser(description="Stonewall tactical briefing CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    today_parser = subparsers.add_parser("today", parents=[common], help="Render the daily tactical brief.")
    today_parser.add_argument("--window-days", type=int, default=45)
    today_parser.add_argument("--recent-days", type=int, default=7)
    today_parser.add_argument("--limit", type=int, default=8)

    case_parser = subparsers.add_parser("case", parents=[common], help="Render a single-case brief.")
    case_parser.add_argument("query")
    case_parser.add_argument("--recent-limit", type=int, default=8)
    return parser


def main() -> int:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        with contextlib.suppress(AttributeError):
            stream.reconfigure(encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args()

    reference_date = parse_iso_date(args.reference_date)
    if reference_date is None:
        raise SystemExit(f"Invalid --date value: {args.reference_date}")

    artifacts = parse_manifest_rows(Path(args.manifest))
    records = parse_case_records(Path(args.case_dates))
    sections = parse_case_sections(Path(args.case_md))
    matchers = build_case_matchers(sections, records)
    report = load_report(Path(args.report))

    if args.command == "today":
        print(render_today(reference_date, artifacts, sections, matchers, report, args.window_days, args.recent_days, args.limit))
        return 0
    if args.command == "case":
        print(render_case(args.query, artifacts, sections, matchers, report, reference_date, args.recent_limit))
        return 0
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
