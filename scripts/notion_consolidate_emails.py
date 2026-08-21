#!/usr/bin/env python3
"""
Notion Email Consolidation Script
Creates a unified email database with all Jan-Mar 2026 emails from
all scattered data sources. One database, three views.
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime

TOKEN = os.environ.get('NOTION_TOKEN', '')
API_VERSION = '2025-09-03'

# Parent page where the main database lives
PARENT_PAGE = os.environ.get('NOTION_PARENT_PAGE', 'YOUR_PARENT_PAGE_ID')

# Pre-created consolidated database (from Phase 2 of previous run)
CONSOLIDATED_DB_ID = os.environ.get('NOTION_ALL_EMAIL_DB', 'YOUR_ALL_EMAIL_DATABASE_ID')
CONSOLIDATED_DS_ID = os.environ.get('NOTION_ALL_EMAIL_DS', 'YOUR_ALL_EMAIL_DATASOURCE_ID')

# All email data sources — populate with the source database/datasource IDs from your Notion workspace.
# Format: (datasource_id, label)
SENT_SOURCES = [
    # ('your-datasource-id-here', 'Sent Emails Dec'),
    # ('your-datasource-id-here', 'Sent Emails Jan'),
]

INBOX_SOURCES = [
    # ('your-datasource-id-here', 'Inbox Emails Jan'),
    # ('your-datasource-id-here', 'Inbox Emails Feb'),
]

# Date range filter (ISO format)
DATE_START = os.environ.get('EMAIL_DATE_START', '2026-01-01')
DATE_END = os.environ.get('EMAIL_DATE_END', '2026-12-31')


def api_request(method, url, data=None, retries=4):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode() if data else None,
                headers={
                    'Authorization': f'Bearer {TOKEN}',
                    'Notion-Version': API_VERSION,
                    'Content-Type': 'application/json'
                },
                method=method
            )
            resp = urllib.request.urlopen(req)
            return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            if e.code == 429:
                retry_after = float(e.headers.get('Retry-After', 1))
                time.sleep(retry_after)
                continue
            elif e.code >= 500:
                time.sleep(2 ** attempt)
                continue
            else:
                if attempt == retries - 1:
                    print(f'  HTTP {e.code}: {body[:200]}')
                return None
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            print(f'  Error: {e}')
            return None
    return None


def parse_date_from_sent_time(text):
    """Parse M.D.YY - H:MM AM/PM format."""
    if not text:
        return None
    m = re.search(
        r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})\s*[-,]?\s*(\d{1,2}):(\d{2})\s*(a\.?m\.?|p\.?m\.?|AM|PM)?',
        text
    )
    if m:
        month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hour, minute = int(m.group(4)), int(m.group(5))
        ampm = m.group(6)
        if year < 100:
            year += 2000
        if ampm:
            ampm_clean = ampm.replace('.', '').upper()
            if ampm_clean == 'PM' and hour < 12:
                hour += 12
            elif ampm_clean == 'AM' and hour == 12:
                hour = 0
        try:
            return datetime(year, month, day, hour, minute).strftime('%Y-%m-%dT%H:%M:00.000+00:00')
        except ValueError:
            pass
    m = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})', text)
    if m:
        month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 2000
        try:
            return datetime(year, month, day).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return None


def get_prop_text(props, *names):
    """Extract text from rich_text or select or title properties."""
    for name in names:
        prop = props.get(name, {})
        t = prop.get('type', '')
        if t == 'rich_text':
            return ''.join(x['plain_text'] for x in prop.get('rich_text', []))
        elif t == 'title':
            return ''.join(x['plain_text'] for x in prop.get('title', []))
        elif t == 'select':
            s = prop.get('select')
            return s['name'] if s else ''
        elif t == 'multi_select':
            return ';'.join(x['name'] for x in prop.get('multi_select', []))
    return ''


def get_date(props, page):
    """Extract date from various possible fields."""
    # Check Date field
    date_prop = props.get('Date', {})
    if date_prop.get('type') == 'date' and date_prop.get('date'):
        return date_prop['date']['start']

    # Check Sent DateTime field
    sent_dt = props.get('Sent DateTime', {})
    if sent_dt.get('type') == 'date' and sent_dt.get('date'):
        return sent_dt['date']['start']

    # Try parsing Sent Time text
    sent_time = get_prop_text(props, 'Sent Time')
    parsed = parse_date_from_sent_time(sent_time)
    if parsed:
        return parsed

    # Fallback to created_time
    created = page.get('created_time', '')
    if created:
        return created[:19] + '.000+00:00'
    return None


def is_in_range(date_str):
    """Check if date is in Jan-Mar 2026 range."""
    if not date_str:
        return True  # Include if we can't tell
    try:
        d = date_str[:10]  # YYYY-MM-DD
        return DATE_START <= d <= DATE_END
    except:
        return True


def fetch_source(ds_id, name, direction):
    """Fetch all records from a data source and normalize."""
    print(f'  Fetching {name}...')
    records = []
    cursor = None
    while True:
        body = {'page_size': 100}
        if cursor:
            body['start_cursor'] = cursor
        resp = api_request('POST',
            f'https://api.notion.com/v1/data_sources/{ds_id}/query', body)
        if not resp:
            print(f'    ERROR fetching')
            return records
        for page in resp['results']:
            props = page['properties']
            subject = get_prop_text(props, '\ufeffSubject', 'Subject', 'Name')
            from_name = get_prop_text(props, 'From: (Name)')
            to_name = get_prop_text(props, 'To: (Name)', 'To: (Name) (1)')
            cc_name = get_prop_text(props, 'CC: (Name)')
            date = get_date(props, page)

            if is_in_range(date):
                records.append({
                    'subject': subject[:2000] if subject else '(no subject)',
                    'from': from_name[:2000] if from_name else '',
                    'to': to_name[:2000] if to_name else '',
                    'cc': cc_name[:2000] if cc_name else '',
                    'date': date,
                    'direction': direction,
                    'source': name,
                })

        if len(records) % 500 == 0 and records:
            print(f'    {len(records)} in range so far...')
        if not resp.get('has_more'):
            break
        cursor = resp['next_cursor']

    print(f'    {len(records)} records in Jan-Mar 2026')
    return records


def create_database(parent_page_id):
    """Create the consolidated email database."""
    print('Creating consolidated database...')
    data = {
        'parent': {'type': 'page_id', 'page_id': parent_page_id},
        'title': [{'type': 'text', 'text': {'content': '📧 All Email — Jan-Mar 2026'}}],
        'properties': {
            'Subject': {'title': {}},
            'From': {'rich_text': {}},
            'To': {'rich_text': {}},
            'CC': {'rich_text': {}},
            'Date': {'date': {}},
            'Direction': {
                'select': {
                    'options': [
                        {'name': 'Sent', 'color': 'blue'},
                        {'name': 'Inbox', 'color': 'green'},
                    ]
                }
            },
            'Source': {
                'select': {
                    'options': []
                }
            },
        }
    }
    resp = api_request('POST', 'https://api.notion.com/v1/databases', data)
    if resp and resp.get('id'):
        db_id = resp['id']
        # Get the data source ID for the new database
        ds_list = resp.get('data_sources', [])
        ds_id = ds_list[0]['id'] if ds_list else None
        print(f'  Database created: {db_id}')
        print(f'  Data source: {ds_id}')
        print(f'  URL: {resp.get("url")}')
        return db_id, ds_id
    else:
        print(f'  ERROR: {resp}')
        return None, None


def insert_records(ds_id, db_id, records):
    """Insert all records into the consolidated database."""
    print(f'\nInserting {len(records)} records...')
    inserted = 0
    errors = 0
    start = time.time()

    for i, rec in enumerate(records):
        props = {
            'Subject': {
                'title': [{'type': 'text', 'text': {'content': rec['subject'][:2000]}}]
            },
            'Date': {
                'date': {'start': rec['date']} if rec['date'] else None
            },
            'Direction': {
                'select': {'name': rec['direction']}
            },
            'Source': {
                'select': {'name': rec['source']}
            },
        }

        # Add rich text fields (handle 2000 char limit)
        for field, key in [('From', 'from'), ('To', 'to'), ('CC', 'cc')]:
            val = rec[key]
            if val:
                props[field] = {
                    'rich_text': [{'type': 'text', 'text': {'content': val[:2000]}}]
                }
            else:
                props[field] = {'rich_text': []}

        page_data = {
            'parent': {
                'type': 'data_source_id',
                'data_source_id': ds_id,
            },
            'properties': props
        }

        result = api_request('POST', 'https://api.notion.com/v1/pages', page_data)
        if result and result.get('object') == 'page':
            inserted += 1
        else:
            errors += 1
            if errors <= 5:
                print(f'  Error on record {i}: {rec["subject"][:50]}')

        if (i + 1) % 100 == 0:
            elapsed = time.time() - start
            rate = (i + 1) / elapsed if elapsed > 0 else 1
            remaining = (len(records) - i - 1) / rate
            print(f'  {i+1}/{len(records)} ({inserted} ok, {errors} err) '
                  f'~{remaining:.0f}s left')

        time.sleep(0.35)

    elapsed = time.time() - start
    print(f'\nInsert complete: {inserted} ok, {errors} errors in {elapsed:.0f}s')
    return inserted, errors


def main():
    print('=== EMAIL CONSOLIDATION — JAN-MAR 2026 ===\n')

    # Phase 1: Fetch all records from all sources
    print('Phase 1: Fetching from all sources...')
    all_records = []

    for ds_id, name in SENT_SOURCES:
        records = fetch_source(ds_id, name, 'Sent')
        all_records.extend(records)

    for ds_id, name in INBOX_SOURCES:
        records = fetch_source(ds_id, name, 'Inbox')
        all_records.extend(records)

    print(f'\nTotal records in Jan-Mar 2026: {len(all_records)}')
    sent_count = sum(1 for r in all_records if r['direction'] == 'Sent')
    inbox_count = sum(1 for r in all_records if r['direction'] == 'Inbox')
    print(f'  Sent: {sent_count}')
    print(f'  Inbox: {inbox_count}')

    if not all_records:
        print('No records found!')
        sys.exit(1)

    # Phase 2: Use pre-created consolidated database
    db_id = CONSOLIDATED_DB_ID
    ds_id = CONSOLIDATED_DS_ID
    print(f'\nPhase 2: Using existing database {db_id}')
    print(f'  Data source: {ds_id}')

    # Phase 3: Insert all records
    print('\nPhase 3: Inserting records...')
    inserted, errors = insert_records(ds_id, db_id, all_records)

    print(f'\n=== CONSOLIDATION COMPLETE ===')
    print(f'Database: {db_id}')
    print(f'Total inserted: {inserted}')
    print(f'Errors: {errors}')
    print(f'Sent: {sent_count}')
    print(f'Inbox: {inbox_count}')


if __name__ == '__main__':
    main()
