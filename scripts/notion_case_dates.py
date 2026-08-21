#!/usr/bin/env python3
"""
Notion Case Dates Script — Stonewall Legal Intelligence Platform
=================================================
Adds case-tracking properties (Date of Loss, Date Complaint Filed,
Reserve, Incurred, Plaintiff Depo, Depo Date, Discovery, Discovery Date)
to the Legal Matters database, then populates them from case_dates.json.

Usage:
  NOTION_TOKEN=ntn_xxx python3 notion_case_dates.py

Options:
  DRY_RUN=1    Preview changes without writing
  SCHEMA_ONLY=1  Only create the properties, skip data population

Date format in case_dates.json: YYYY-MM-DD or M/D/YYYY (e.g. "2024-03-15" or "3/15/2024")
Number format: plain integer/float, or "$300,000" with optional $ and commas
Checkbox format: "yes"/"no"/"true"/"false"/"y"/"n"/"1"/"0"
Leave blank ("") to skip that field for a case.
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime

# ── Config ──────────────────────────────────────────────────────────────────
TOKEN = os.environ.get('NOTION_TOKEN', '')
API_VERSION = '2022-06-28'
DRY_RUN = os.environ.get('DRY_RUN', '0') == '1'
SCHEMA_ONLY = os.environ.get('SCHEMA_ONLY', '0') == '1'

LEGAL_MATTERS_DB = os.environ.get('NOTION_LEGAL_MATTERS_DB', 'YOUR_LEGAL_MATTERS_DATABASE_ID')

PROP_DOL = 'Date of Loss'
PROP_COMPLAINT = 'Date Complaint Filed'
PROP_RESERVE = 'Reserve'
PROP_INCURRED = 'Incurred'
PROP_PTF_DEPO = 'Plaintiff Depo'
PROP_DEPO_DATE = 'Depo Date'
PROP_DISCOVERY = 'Discovery'
PROP_DISCO_DATE = 'Discovery Date'

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CASE_DATES_FILE = os.path.join(SCRIPT_DIR, 'case_dates.json')


# ── API Helper ───────────────────────────────────────────────────────────────
def api(method, endpoint, data=None, retries=4):
    url = f'https://api.notion.com/v1/{endpoint}'
    for attempt in range(retries):
        try:
            body = json.dumps(data).encode() if data else None
            req = urllib.request.Request(url, data=body, headers={
                'Authorization': f'Bearer {TOKEN}',
                'Notion-Version': API_VERSION,
                'Content-Type': 'application/json',
            }, method=method)
            resp = urllib.request.urlopen(req, timeout=30)
            return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body_text = e.read().decode() if e.fp else ''
            if e.code == 429:
                wait = float(e.headers.get('Retry-After', 2 * (attempt + 1)))
                print(f'  Rate limited. Waiting {wait:.0f}s...')
                time.sleep(wait)
                continue
            elif e.code in (409, 500, 502, 503) and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            else:
                print(f'  API Error {e.code}: {body_text[:300]}')
                raise
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            if attempt < retries - 1:
                wait = 2 ** (attempt + 1)
                print(f'  Network error: {e}. Retrying in {wait}s...')
                time.sleep(wait)
                continue
            print(f'  Network error after {retries} retries: {e}')
            raise
    raise RuntimeError(f'Failed after {retries} retries: {method} {endpoint}')


def paginate_db(db_id, page_size=100):
    pages = []
    cursor = None
    while True:
        body = {'page_size': page_size}
        if cursor:
            body['start_cursor'] = cursor
        result = api('POST', f'databases/{db_id}/query', body)
        pages.extend(result.get('results', []))
        if not result.get('has_more'):
            break
        cursor = result.get('next_cursor')
        if not cursor:
            break
        time.sleep(0.35)
    return pages


# ── Schema: Ensure properties exist ───────────────────────────────────────────
SCHEMA_FIELDS = {
    PROP_DOL:       {'date': {}},
    PROP_COMPLAINT: {'date': {}},
    PROP_RESERVE:   {'number': {'format': 'dollar'}},
    PROP_INCURRED:  {'number': {'format': 'dollar'}},
    PROP_PTF_DEPO:  {'checkbox': {}},
    PROP_DEPO_DATE: {'date': {}},
    PROP_DISCOVERY: {'checkbox': {}},
    PROP_DISCO_DATE:{'date': {}},
}

def ensure_properties():
    """Create all case-tracking properties on Legal Matters if missing."""
    db = api('GET', f'databases/{LEGAL_MATTERS_DB}')
    existing = db.get('properties', {})

    to_create = {}
    for prop_name, type_config in SCHEMA_FIELDS.items():
        expected_type = list(type_config.keys())[0]
        if prop_name in existing:
            actual_type = existing[prop_name].get('type')
            if actual_type == expected_type:
                print(f'  ✓ "{prop_name}" already exists ({expected_type})')
            else:
                print(f'  ✗ Schema error: "{prop_name}" exists on Legal Matters '
                      f'but is type "{actual_type}", expected "{expected_type}".')
                print(f'    Please update this property in Notion and re-run.')
                sys.exit(1)
        else:
            to_create[prop_name] = type_config
            print(f'  + Will create "{prop_name}" ({expected_type})')

    if not to_create:
        print('  No schema changes needed.')
        return

    if DRY_RUN:
        print(f'  [DRY RUN] Would create: {list(to_create.keys())}')
        return

    print(f'  Creating {len(to_create)} properties on Legal Matters...')
    api('PATCH', f'databases/{LEGAL_MATTERS_DB}', {'properties': to_create})
    print('  ✓ Schema updated')
    time.sleep(1)


# ── Data: Validate date strings ───────────────────────────────────────────────
def parse_date(value):
    """Return ISO date string or None. Accepts YYYY-MM-DD or M/D/YYYY."""
    if not value or not value.strip():
        return None
    v = value.strip()
    # Accept YYYY-MM-DD
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', v):
        try:
            datetime.strptime(v, '%Y-%m-%d')
            return v
        except ValueError:
            pass
    # Accept M/D/YYYY or MM/DD/YYYY
    m = re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{4})', v)
    if m:
        try:
            dt = datetime(int(m.group(3)), int(m.group(1)), int(m.group(2)))
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            pass
    print(f'  ⚠ Unrecognized date format: "{v}" — skipping')
    return None


# ── Data: Parse numbers ───────────────────────────────────────────────────────
def parse_number(raw):
    """Parse a number from JSON. Handles $, commas, and zero values."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if not s:
        return None
    # Strip currency symbols and commas
    s = re.sub(r'[$,\s]', '', s)
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        print(f'  ⚠ Invalid number: "{raw}" — skipping')
        return None


# ── Data: Parse checkboxes ────────────────────────────────────────────────────
def parse_checkbox(raw):
    """Parse a boolean from JSON. Empty string = not provided, 'no' = False."""
    if raw is None or raw == '':
        return None
    s = str(raw).strip().lower()
    if not s:
        return None
    return s in ('yes', 'true', '1', 'y')


# ── Data: Validate case_dates.json ────────────────────────────────────────────
def validate_case_data(case_dates):
    """Check for duplicate IDs and warn. Returns the ID→entry map."""
    by_id = {}
    duplicates = []
    for c in case_dates:
        clean_id = c['id'].replace('-', '')
        if not clean_id:
            continue
        if clean_id in by_id:
            duplicates.append((clean_id, by_id[clean_id]['name'], c['name']))
        by_id[clean_id] = c

    if duplicates:
        print('  ⚠ Duplicate Notion page IDs detected:')
        for dup_id, name1, name2 in duplicates:
            print(f'    ID {dup_id[:12]}... shared by:')
            print(f'      1. {name1}')
            print(f'      2. {name2} (will overwrite #1 in ID lookup)')
        print('    These cases will fall back to name matching.')
        print()

    return by_id


# ── Data: Populate case dates ─────────────────────────────────────────────────
def populate_dates(case_dates):
    """
    For each entry in case_dates that has data,
    update the corresponding Legal Matters page.
    Matches by page ID first, then falls back to exact case name match.
    """
    # Build ID → entry map with duplicate validation
    by_id = validate_case_data(case_dates)

    # Load all Legal Matters pages
    print('  Fetching Legal Matters pages...')
    pages = paginate_db(LEGAL_MATTERS_DB)
    print(f'  Found {len(pages)} cases in Notion')

    updated = 0
    would_update = 0
    skipped = 0
    errors = 0

    for page in pages:
        page_id_clean = page['id'].replace('-', '')
        props = page.get('properties', {})

        # Get case name for logging
        case_name = ''.join(
            t.get('plain_text', '')
            for t in props.get('Case Name', {}).get('title', [])
        )

        # Match by page ID
        entry = by_id.get(page_id_clean)
        if not entry:
            # Fallback: exact case-insensitive name match
            name_lower = case_name.lower()
            for c in case_dates:
                if c['name'].lower() == name_lower:
                    entry = c
                    break

        if not entry:
            skipped += 1
            continue

        # Parse all fields from the entry
        dol = parse_date(entry.get('dol', ''))
        complaint = parse_date(entry.get('complaint_filed', ''))
        depo_date = parse_date(entry.get('depo_date', ''))
        disco_date = parse_date(entry.get('disco_date', ''))
        reserve = parse_number(entry.get('reserve', ''))
        incurred = parse_number(entry.get('incurred', ''))
        ptf_depo = parse_checkbox(entry.get('plaintiff_depo', ''))
        disco = parse_checkbox(entry.get('discovery', ''))

        # Skip if nothing to set
        has_data = any(x is not None for x in [dol, complaint, depo_date, disco_date,
                                                 reserve, incurred, ptf_depo, disco])
        if not has_data:
            skipped += 1
            continue

        # Check existing values to avoid unnecessary writes
        def date_matches(prop_name, new_val):
            if new_val is None:
                return True
            existing = (props.get(prop_name, {}).get('date') or {}).get('start', '')
            return existing[:10] == new_val

        def num_matches(prop_name, new_val):
            if new_val is None:
                return True
            existing = props.get(prop_name, {}).get('number')
            return existing == new_val

        def cb_matches(prop_name, new_val):
            if new_val is None:
                return True
            existing = props.get(prop_name, {}).get('checkbox')
            return existing == new_val

        all_match = (date_matches(PROP_DOL, dol) and
                     date_matches(PROP_COMPLAINT, complaint) and
                     date_matches(PROP_DEPO_DATE, depo_date) and
                     date_matches(PROP_DISCO_DATE, disco_date) and
                     num_matches(PROP_RESERVE, reserve) and
                     num_matches(PROP_INCURRED, incurred) and
                     cb_matches(PROP_PTF_DEPO, ptf_depo) and
                     cb_matches(PROP_DISCOVERY, disco))

        if all_match:
            skipped += 1
            continue

        # Build update payload — only include changed fields
        update_props = {}
        if dol and not date_matches(PROP_DOL, dol):
            update_props[PROP_DOL] = {'date': {'start': dol}}
        if complaint and not date_matches(PROP_COMPLAINT, complaint):
            update_props[PROP_COMPLAINT] = {'date': {'start': complaint}}
        if depo_date and not date_matches(PROP_DEPO_DATE, depo_date):
            update_props[PROP_DEPO_DATE] = {'date': {'start': depo_date}}
        if disco_date and not date_matches(PROP_DISCO_DATE, disco_date):
            update_props[PROP_DISCO_DATE] = {'date': {'start': disco_date}}
        if reserve is not None and not num_matches(PROP_RESERVE, reserve):
            update_props[PROP_RESERVE] = {'number': reserve}
        if incurred is not None and not num_matches(PROP_INCURRED, incurred):
            update_props[PROP_INCURRED] = {'number': incurred}
        if ptf_depo is not None and not cb_matches(PROP_PTF_DEPO, ptf_depo):
            update_props[PROP_PTF_DEPO] = {'checkbox': ptf_depo}
        if disco is not None and not cb_matches(PROP_DISCOVERY, disco):
            update_props[PROP_DISCOVERY] = {'checkbox': disco}

        if not update_props:
            skipped += 1
            continue

        if DRY_RUN:
            fields = ', '.join(f'{k}' for k in update_props)
            print(f'  [DRY RUN] {case_name[:40]:40} → {fields}')
            would_update += 1
            continue

        try:
            api('PATCH', f'pages/{page["id"]}', {'properties': update_props})
            updated += 1
            parts = [k for k in update_props]
            print(f'  ✓ {case_name[:40]:40} → {", ".join(parts)}')
            time.sleep(0.35)
        except Exception as e:
            errors += 1
            print(f'  ✗ {case_name[:45]} — {e}')

    if DRY_RUN:
        print(f'\n  Would update: {would_update} | Skipped/no data: {skipped}')
    else:
        print(f'\n  Updated: {updated} | Skipped/no data: {skipped} | Errors: {errors}')
    return updated or would_update, errors


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if not TOKEN:
        print('ERROR: Set NOTION_TOKEN environment variable')
        sys.exit(1)

    mode = 'DRY RUN' if DRY_RUN else 'LIVE'
    print(f'═══ Stonewall Case Dates ({mode}) ═══')
    print(f'Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print()

    # Phase 1: Schema
    print('Phase 1: Ensuring properties on Legal Matters...')
    ensure_properties()
    print()

    if SCHEMA_ONLY:
        print('SCHEMA_ONLY=1 — skipping data population.')
        return

    # Phase 2: Load case_dates.json
    print(f'Phase 2: Loading {CASE_DATES_FILE}...')
    try:
        with open(CASE_DATES_FILE, encoding='utf-8') as f:
            case_dates = json.load(f)
    except FileNotFoundError:
        print(f'ERROR: {CASE_DATES_FILE} not found')
        sys.exit(1)

    # Filter to only cases that have at least one field populated
    data_fields = ('dol', 'complaint_filed', 'reserve', 'incurred',
                   'plaintiff_depo', 'depo_date', 'discovery', 'disco_date')
    has_data = [c for c in case_dates if any(c.get(f) for f in data_fields)]
    print(f'  {len(case_dates)} cases in file, {len(has_data)} have data')
    print()

    if not has_data:
        print('No data populated in case_dates.json yet.')
        print('Fill in fields and re-run. Dates: YYYY-MM-DD or M/D/YYYY. Numbers: plain or $1,000. Checkboxes: yes/no.')
        print()
        print('Example:')
        print('  { "name": "Smith v. Acme Corp", "dol": "2023-06-15", '
              '"complaint_filed": "2024-01-10",')
        print('    "reserve": 300000, "incurred": 45000, "plaintiff_depo": "yes", '
              '"depo_date": "2025-10-17",')
        print('    "discovery": "no", "disco_date": "" }')
        return

    # Phase 3: Populate
    print('Phase 3: Populating case dates in Notion...')
    populate_dates(case_dates)

    print()
    print('═══ COMPLETE ═══')
    print()
    print('Next steps:')
    print('  1. Fill in case_dates.json with all case data')
    print('  2. Re-run this script to push updates to Notion')
    print('  3. In Legal Matters, sort/filter by Date of Loss for case aging views')


if __name__ == '__main__':
    main()
