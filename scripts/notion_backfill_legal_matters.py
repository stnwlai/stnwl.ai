#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from tactical_brief import (
    DEFAULT_CASE_DATES,
    DEFAULT_CASE_MD,
    DEFAULT_MANIFEST,
    artifact_case_headings,
    build_upcoming_items,
    build_case_matchers,
    compact_whitespace,
    find_open_loops,
    normalize_claim,
    parse_case_records,
    parse_case_sections,
    parse_manifest_rows,
    resolve_case_heading,
    score_text_match,
    tokenize,
    truncate,
)

LEGAL_MATTERS_DS_ID = os.environ.get("NOTION_LEGAL_MATTERS_DB", "YOUR_LEGAL_MATTERS_DATABASE_ID")
NOTION_API_VERSION = "2025-09-03"
TODAY = date.today().isoformat()


@dataclass(frozen=True)
class PageState:
    page_id: str
    title: str
    url: str
    properties: dict
    child_count: int


def notion_api(token: str, method: str, endpoint: str, data: dict | None = None, retries: int = 4) -> dict:
    url = f"https://api.notion.com/v1/{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }
    for attempt in range(retries):
        try:
            body = json.dumps(data).encode("utf-8") if data is not None else None
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            with urllib.request.urlopen(req) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
            if exc.code == 429 and attempt < retries - 1:
                delay = float(exc.headers.get("Retry-After", 2 * (attempt + 1)))
                time.sleep(delay)
                continue
            if exc.code == 409 and attempt < retries - 1:
                time.sleep(1.5)
                continue
            raise RuntimeError(f"Notion API error {exc.code} on {method} {endpoint}: {payload[:400]}") from exc
    raise RuntimeError(f"Notion API failed after {retries} retries: {method} {endpoint}")


def paginate_data_source(token: str, data_source_id: str) -> list[dict]:
    pages: list[dict] = []
    cursor: str | None = None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        payload = notion_api(token, "POST", f"data_sources/{data_source_id}/query", body)
        pages.extend(payload.get("results", []))
        if not payload.get("has_more"):
            return pages
        cursor = payload.get("next_cursor")


def get_children(token: str, block_id: str) -> list[dict]:
    children: list[dict] = []
    cursor: str | None = None
    while True:
        endpoint = f"blocks/{block_id}/children?page_size=100"
        if cursor:
            endpoint += "&start_cursor=" + urllib.parse.quote(cursor)
        payload = notion_api(token, "GET", endpoint)
        children.extend(payload.get("results", []))
        if not payload.get("has_more"):
            return children
        cursor = payload.get("next_cursor")
        time.sleep(0.1)


def get_title(props: dict, name: str = "Case Name") -> str:
    parts = props.get(name, {}).get("title", [])
    return "".join(part.get("plain_text", "") for part in parts).strip()


def get_rich_text(props: dict, name: str) -> str:
    parts = props.get(name, {}).get("rich_text", [])
    return "".join(part.get("plain_text", "") for part in parts).strip()


def get_select(props: dict, name: str) -> str:
    return (props.get(name, {}).get("select") or {}).get("name", "") or ""


def get_date(props: dict, name: str) -> str:
    return (props.get(name, {}).get("date") or {}).get("start", "") or ""


def get_checkbox(props: dict, name: str) -> bool | None:
    prop = props.get(name, {})
    if prop.get("type") != "checkbox":
        return None
    return prop.get("checkbox")


def get_number(props: dict, name: str) -> float | int | None:
    prop = props.get(name, {})
    if prop.get("type") != "number":
        return None
    return prop.get("number")


def notion_rich_text(text: str) -> list[dict]:
    return [{"type": "text", "text": {"content": text[:1900]}}]


def heading_1(text: str) -> dict:
    return {"object": "block", "type": "heading_1", "heading_1": {"rich_text": notion_rich_text(text)}}


def heading_2(text: str) -> dict:
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": notion_rich_text(text)}}


def paragraph(text: str) -> dict:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": notion_rich_text(text)}}


def bullet(text: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": notion_rich_text(text)},
    }


def divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def parse_money(value: str) -> float | None:
    text = value.strip()
    if not text:
        return None
    cleaned = text.replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def value_present(props: dict, name: str) -> bool:
    prop = props.get(name, {})
    typ = prop.get("type")
    if typ == "title":
        return bool(get_title(props, name))
    if typ == "rich_text":
        return bool(get_rich_text(props, name))
    if typ == "date":
        return bool(get_date(props, name))
    if typ == "select":
        return bool(get_select(props, name))
    if typ == "checkbox":
        return get_checkbox(props, name) is not None
    if typ == "number":
        return get_number(props, name) is not None
    return False


def build_select_payload(name: str) -> dict:
    return {"select": {"name": name}}


def build_rich_payload(text: str) -> dict:
    return {"rich_text": notion_rich_text(text)}


def build_date_payload(value: str) -> dict:
    return {"date": {"start": value}}


def build_checkbox_payload(value: bool) -> dict:
    return {"checkbox": value}


def build_number_payload(value: float) -> dict:
    return {"number": value}


def match_case_record(page_title: str, records: list) -> object | None:
    best_score = 0
    best_record = None
    for record in records:
        claims = {normalize_claim(record.claim)} if record.claim else set()
        score = score_text_match(page_title, tokenize(record.name), claims, record.name)
        if score > best_score:
            best_score = score
            best_record = record
    return best_record if best_score > 0 else None


def normalize_case_name(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\([^)]*\)", "", text.lower()))


def extract_plaintiff_tokens(text: str) -> set[str]:
    lead = re.split(r"\s+v\.?\s+", text, maxsplit=1, flags=re.IGNORECASE)[0]
    stopwords = {"estate", "minor", "of", "the", "and"}
    return {token for token in tokenize(lead) if token not in stopwords}


def match_section_for_page(page_title: str, record, matchers: dict, sections: dict) -> str | None:
    candidate = resolve_case_heading(page_title, matchers)
    if not candidate:
        return None
    matcher = matchers[candidate]
    if record and matcher.record:
        if normalize_case_name(matcher.record.name) == normalize_case_name(record.name):
            return candidate
    plaintiff_tokens = extract_plaintiff_tokens(page_title)
    if not plaintiff_tokens:
        return candidate
    descriptor = candidate
    if candidate in sections:
        descriptor = " ".join(
            filter(
                None,
                [
                    candidate,
                    sections[candidate].fields.get("Style", ""),
                    sections[candidate].fields.get("Plaintiffs", ""),
                    sections[candidate].fields.get("Plaintiff", ""),
                ],
            )
        )
    if plaintiff_tokens & tokenize(descriptor):
        return candidate
    return None


def artifacts_for_record(page_title: str, record, artifacts: list) -> list:
    query = f"{page_title} {record.name if record else ''}"
    claims = {normalize_claim(record.claim)} if record and record.claim else set()
    plaintiff_tokens = extract_plaintiff_tokens(record.name if record else page_title)
    matches: list[tuple[int, object]] = []
    for artifact in artifacts:
        haystack = " ".join((artifact.case_field, artifact.file_field, artifact.summary))
        score = score_text_match(query, tokenize(haystack), claims, haystack)
        artifact_tokens = tokenize(haystack)
        if score > 0 and (plaintiff_tokens & artifact_tokens or score >= 10):
            matches.append((score, artifact))
    matches.sort(key=lambda row: (-row[0], -(row[1].artifact_date or date.min).toordinal(), row[1].artifact_id))
    deduped: list = []
    seen: set[str] = set()
    for _, artifact in matches:
        if artifact.artifact_id in seen:
            continue
        deduped.append(artifact)
        seen.add(artifact.artifact_id)
    return deduped


def flatten_section_lines(section) -> list[str]:
    lines: list[str] = []
    for field_name in ("Key Discovery", "Key Events", "Mediation", "Projected Trial", "Demand", "Experts", "Injuries"):
        value = section.fields.get(field_name, "")
        if value:
            lines.append(f"{field_name}: {compact_whitespace(value)}")
        for item in section.lists.get(field_name, []):
            lines.append(compact_whitespace(item))
    deduped: list[str] = []
    seen: set[str] = set()
    for item in lines:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped


def normalize_note_line(text: str) -> str:
    return re.sub(r"^[A-Za-z /'-]+:\s*", "", compact_whitespace(text)).lower()


def choose_notes_text(section, artifacts: list) -> str:
    if section:
        loops = find_open_loops(section)
        if loops:
            return truncate(loops[0], 180)
        lines = flatten_section_lines(section)
        if lines:
            return truncate(lines[0], 180)
    if artifacts:
        return truncate(artifacts[0].summary, 180)
    return ""


def extract_first_date(text: str) -> str:
    match = re.search(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b", text)
    if not match:
        return ""
    raw = match.group(1)
    month, day, year = raw.split("/")
    year = f"20{year}" if len(year) == 2 else year
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def derive_property_updates(page: PageState, section, record, upcoming: list, artifacts: list) -> dict:
    props = page.properties
    updates: dict[str, dict] = {}

    def set_if_blank(name: str, payload: dict | None) -> None:
        if not payload or value_present(props, name):
            return
        updates[name] = payload

    if record and record.claim:
        set_if_blank("Claim Number", build_rich_payload(record.claim))
    if section:
        if value := section.fields.get("Case No.", ""):
            set_if_blank("Case Number", build_rich_payload(value))
        plaintiff = section.fields.get("Plaintiffs") or section.fields.get("Plaintiff") or ""
        if plaintiff:
            set_if_blank("Plaintiff", build_rich_payload(plaintiff))
        if driver := section.fields.get("Carrier Driver", ""):
            set_if_blank("Carrier Driver", build_rich_payload(driver))
        if oc := section.fields.get("OC") or section.fields.get("Plaintiff's Counsel") or "":
            set_if_blank("Opposing Counsel", build_rich_payload(oc))
            if not value_present(props, "OC Firm"):
                firm_match = re.search(r"\(([^)]+)\)", oc)
                if firm_match:
                    updates["OC Firm"] = build_rich_payload(firm_match.group(1))
        if adjuster := section.fields.get("Adjuster", ""):
            set_if_blank("Adjuster", build_rich_payload(adjuster))
        if injuries := section.fields.get("Injuries", ""):
            set_if_blank("Injury Type", build_rich_payload(injuries))
        if mediation_text := section.fields.get("Mediation", ""):
            mediation_date = extract_first_date(mediation_text)
            if mediation_date:
                set_if_blank("Mediation Date", build_date_payload(mediation_date))
        if trial_text := section.fields.get("Projected Trial", ""):
            trial_date = extract_first_date(trial_text)
            if trial_date:
                set_if_blank("Trial Date", build_date_payload(trial_date))

    if record:
        reserve = parse_money(record.reserve)
        incurred = parse_money(record.incurred)
        if reserve is not None:
            set_if_blank("Reserve", build_number_payload(reserve))
        if incurred is not None:
            set_if_blank("Incurred", build_number_payload(incurred))
        raw = record.raw
        depo_flag = raw.get("plaintiff_depo", "").strip().lower()
        if depo_flag in {"yes", "no"}:
            set_if_blank("Plaintiff Depo", build_checkbox_payload(depo_flag == "yes"))
        discovery_flag = raw.get("discovery", "").strip().lower()
        if discovery_flag in {"yes", "no"}:
            set_if_blank("Discovery", build_checkbox_payload(discovery_flag == "yes"))
        if record.depo_date:
            set_if_blank("Depo Date", build_date_payload(record.depo_date.isoformat()))
        if record.disco_date:
            set_if_blank("Discovery Date", build_date_payload(record.disco_date.isoformat()))
        if record.complaint_filed:
            date_payload = build_date_payload(record.complaint_filed.isoformat())
            set_if_blank("Date Complaint Filed", date_payload)
            set_if_blank("Date of Complaint", date_payload)

    if not value_present(props, "Next Deadline"):
        future = [item for item in upcoming if item.when >= date.today()]
        if future:
            updates["Next Deadline"] = build_date_payload(future[0].when.isoformat())

    notes_text = choose_notes_text(section, artifacts)
    if notes_text:
        set_if_blank("Notes", build_rich_payload(notes_text))

    return updates


def dedupe_upcoming_items(items: list) -> list:
    by_label: dict[str, object] = {}
    for item in items:
        existing = by_label.get(item.label)
        if existing is None or item.when < existing.when:
            by_label[item.label] = item
    return sorted(by_label.values(), key=lambda item: (item.when, item.label))


def build_snapshot_lines(page: PageState, section, record, upcoming: list, artifacts: list) -> list[str]:
    props = page.properties
    lines: list[str] = []

    def add(label: str, value: str) -> None:
        if value:
            lines.append(f"{label}: {compact_whitespace(value)}")

    add("Case Name", page.title)
    add("Claim Number", record.claim if record else get_rich_text(props, "Claim Number"))
    add("Case Number", (section.fields.get("Case No.", "") if section else "") or get_rich_text(props, "Case Number"))
    plaintiff = ""
    if section:
        plaintiff = section.fields.get("Plaintiffs") or section.fields.get("Plaintiff") or ""
    add("Plaintiff", plaintiff or get_rich_text(props, "Plaintiff"))
    add("Carrier Driver", (section.fields.get("Carrier Driver", "") if section else "") or get_rich_text(props, "Carrier Driver"))
    add("Opposing Counsel", (section.fields.get("OC", "") if section else "") or get_rich_text(props, "Opposing Counsel"))
    add("Adjuster", (section.fields.get("Adjuster", "") if section else "") or get_rich_text(props, "Adjuster"))
    add("Injuries", (section.fields.get("Injuries", "") if section else "") or get_rich_text(props, "Injury Type"))

    if record and record.reserve:
        add("Reserve", record.reserve)
    if record and record.incurred:
        add("Incurred", record.incurred)
    if record and record.depo_date:
        add("Depo Date", record.depo_date.isoformat())
    if record and record.disco_date:
        add("Discovery Date", record.disco_date.isoformat())
    if record:
        raw = record.raw
        if raw.get("plaintiff_depo", "").strip().lower() in {"yes", "no"}:
            add("Plaintiff Depo", raw["plaintiff_depo"].strip().title())
        if raw.get("discovery", "").strip().lower() in {"yes", "no"}:
            add("Discovery", raw["discovery"].strip().title())

    if section:
        if mediation := section.fields.get("Mediation", ""):
            add("Mediation", mediation)
        if trial := section.fields.get("Projected Trial", ""):
            add("Projected Trial", trial)
        if demand := section.fields.get("Demand", ""):
            add("Demand", demand)

    if upcoming:
        next_item = upcoming[0]
        add("Next Dated Item", f"{next_item.when.isoformat()} — {next_item.label}")
    if artifacts:
        latest = artifacts[0]
        add("Latest Artifact", f"{latest.raw_date or '—'} — {latest.artifact_id} — {truncate(latest.summary, 120)}")

    deduped: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if line not in seen:
            deduped.append(line)
            seen.add(line)
    return deduped


def build_body_blocks(page: PageState, section, record, upcoming: list, artifacts: list) -> list[dict]:
    blocks: list[dict] = [
        heading_1(page.title),
        paragraph(
            "Corpus backfill completed "
            f"{TODAY} from catalog/index_by_case.md, scripts/case_dates.json, and catalog/manifest.md."
        ),
        divider(),
        heading_2("Snapshot"),
    ]
    for line in build_snapshot_lines(page, section, record, upcoming, artifacts)[:10]:
        blocks.append(bullet(line))

    corpus_notes = flatten_section_lines(section) if section else []
    open_loops = find_open_loops(section) if section else []
    if open_loops or corpus_notes:
        blocks.extend([divider(), heading_2("Corpus Notes")])
        seen_notes = {normalize_note_line(item) for item in open_loops}
        for line in open_loops[:4]:
            blocks.append(bullet(truncate(line, 200)))
        for line in corpus_notes[:6]:
            if normalize_note_line(line) not in seen_notes:
                blocks.append(bullet(truncate(line, 200)))

    clean_upcoming = dedupe_upcoming_items(upcoming)
    if clean_upcoming:
        blocks.extend([divider(), heading_2("Upcoming")])
        for item in clean_upcoming[:5]:
            blocks.append(bullet(f"{item.when.isoformat()} — {truncate(item.label, 180)}"))

    if artifacts:
        blocks.extend([divider(), heading_2("Corpus Artifacts")])
        for artifact in artifacts[:6]:
            line = f"{artifact.artifact_id} ({artifact.raw_date or '—'}) — {truncate(artifact.summary, 180)}"
            blocks.append(bullet(line))
    else:
        blocks.extend(
            [
                divider(),
                paragraph("No dedicated case-specific artifacts are presently matched in the repo-local corpus."),
            ]
        )

    if not section:
        blocks.append(paragraph("No dedicated section for this matter is currently cataloged in catalog/index_by_case.md."))

    return blocks[:95]


def collect_pages(token: str, data_source_id: str) -> list[PageState]:
    pages: list[PageState] = []
    for page in paginate_data_source(token, data_source_id):
        props = page.get("properties", {})
        page_id = page["id"]
        children = get_children(token, page_id)
        pages.append(
            PageState(
                page_id=page_id,
                title=get_title(props),
                url=page.get("url", ""),
                properties=props,
                child_count=len(children),
            )
        )
    pages.sort(key=lambda item: item.title.lower())
    return pages


def append_body(token: str, page_id: str, blocks: list[dict]) -> None:
    notion_api(token, "PATCH", f"blocks/{page_id}/children", {"children": blocks})


def update_properties(token: str, page_id: str, properties: dict) -> None:
    notion_api(token, "PATCH", f"pages/{page_id}", {"properties": properties})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill blank Legal Matters pages from the local Stonewall corpus.")
    parser.add_argument("--data-source-id", default=LEGAL_MATTERS_DS_ID)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--case-dates", default=str(DEFAULT_CASE_DATES))
    parser.add_argument("--case-md", default=str(DEFAULT_CASE_MD))
    parser.add_argument("--limit", type=int, default=0, help="Optional cap on blank pages to process.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only-title", action="append", dest="only_titles", help="Restrict to matching page titles.")
    return parser


def main() -> int:
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    args = build_parser().parse_args()
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        print("ERROR: NOTION_TOKEN is required.", file=sys.stderr)
        return 1

    artifacts = parse_manifest_rows(Path(args.manifest))
    records = parse_case_records(Path(args.case_dates))
    sections = parse_case_sections(Path(args.case_md))
    matchers = build_case_matchers(sections, records)
    artifacts_by_heading: dict[str, list] = defaultdict(list)
    for artifact in artifacts:
        for heading in artifact_case_headings(artifact, matchers):
            artifacts_by_heading[heading].append(artifact)
    for bucket in artifacts_by_heading.values():
        bucket.sort(key=lambda item: (item.artifact_date or date.min, item.artifact_id), reverse=True)

    pages = collect_pages(token, args.data_source_id)
    blank_pages = [page for page in pages if page.child_count == 0 and page.title]
    if args.only_titles:
        requested = {item.lower() for item in args.only_titles}
        blank_pages = [page for page in blank_pages if page.title.lower() in requested]
    if args.limit > 0:
        blank_pages = blank_pages[: args.limit]

    upcoming = build_upcoming_items(date.today(), 180, sections, matchers)
    processed = 0
    property_updates_total = 0
    for page in blank_pages:
        record = match_case_record(page.title, records)
        heading = match_section_for_page(page.title, record, matchers, sections)
        section = sections.get(heading) if heading else None
        page_upcoming = [item for item in upcoming if item.case_heading == heading][:5] if heading else []
        page_artifacts = artifacts_by_heading.get(heading, []) if heading else artifacts_for_record(page.title, record, artifacts)
        prop_updates = derive_property_updates(page, section, record, page_upcoming, page_artifacts)
        body_blocks = build_body_blocks(page, section, record, page_upcoming, page_artifacts)

        print(
            f"{page.title} | section={heading or '—'} | record={record.name if record else '—'} | "
            f"props={len(prop_updates)} | blocks={len(body_blocks)}"
        )
        if args.dry_run:
            processed += 1
            property_updates_total += len(prop_updates)
            continue

        if prop_updates:
            update_properties(token, page.page_id, prop_updates)
            property_updates_total += len(prop_updates)
        append_body(token, page.page_id, body_blocks)
        processed += 1
        time.sleep(0.25)

    mode = "Dry run" if args.dry_run else "Updated"
    print(f"{mode}: {processed} blank pages processed; {property_updates_total} property updates planned/applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
