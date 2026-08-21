#!/usr/bin/env python3
"""
Fast Notion Email Consolidation — uses concurrent.futures for parallel inserts.
Picks up where the previous run left off by checking existing records.
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

TOKEN = os.environ.get('NOTION_TOKEN', '')
API_VERSION = '2025-09-03'

CONSOLIDATED_DS_ID = os.environ.get('NOTION_ALL_EMAIL_DS', 'YOUR_ALL_EMAIL_DATASOURCE_ID')

# Populate with the source datasource IDs from your Notion workspace.
# Format: (datasource_id, label)
SENT_SOURCES = [
    # ('your-datasource-id-here', 'Sent Emails Dec'),
    # ('your-datasource-id-here', 'Sent Emails Jan'),
]

INBOX_SOURCES = [
    # ('your-datasource-id-here', 'Inbox Emails Jan'),
    # ('your-datasource-id-here', 'Inbox Emails Feb'),
]

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
                time.sleep(retry_after + 0.5)
                continue
            elif e.code >= 500:
                time.sleep(2 ** attempt)
                continue
            else:
                return None
        except Exception:
            if attempt < retries - 1:
                time.sleep(1)
                continue
            return None
    return None


def parse_date_from_sent_time(text):
    if not text:
        return None
    m = re.search(
        r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})\s*[-,]?\s*(\d{1,2}):(\d{2})\s*(a\.?m\.?|p\.?m\.?|AM|PM)?',
        text)
    if m:
        month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hour, minute = int(m.group(4)), int(m.group(5))
        ampm = m.group(6)
        if year < 100: year += 2000
        if ampm:
            ac = ampm.replace('.', '').upper()
            if ac == 'PM' and hour < 12: hour += 12
            elif ac == 'AM' and hour == 12: hour = 0
        try:
            return datetime(year, month, day, hour, minute).strftime('%Y-%m-%dT%H:%M:00.000+00:00')
        except ValueError:
            pass
    m = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})', text)
    if m:
        month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100: year += 2000
        try:
            return datetime(year, month, day).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return None


def get_prop_text(props, *names):
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
    date_prop = props.get('Date', {})
    if date_prop.get('type') == 'date' and date_prop.get('date'):
        return date_prop['date']['start']
    sent_dt = props.get('Sent DateTime', {})
    if sent_dt.get('type') == 'date' and sent_dt.get('date'):
        return sent_dt['date']['start']
    sent_time = get_prop_text(props, 'Sent Time')
    parsed = parse_date_from_sent_time(sent_time)
    if parsed:
        return parsed
    created = page.get('created_time', '')
    if created:
        return created[:19] + '.000+00:00'
    return None


def is_in_range(date_str):
    if not date_str:
        return True
    try:
        return DATE_START <= date_str[:10] <= DATE_END
    except:
        return True


def fetch_source(ds_id, name, direction):
    print(f'  Fetching {name}...', flush=True)
    records = []
    cursor = None
    while True:
        body = {'page_size': 100}
        if cursor:
            body['start_cursor'] = cursor
        resp = api_request('POST',
            f'https://api.notion.com/v1/data_sources/{ds_id}/query', body)
        if not resp:
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
                    'subject': (subject or '(no subject)')[:2000],
                    'from': (from_name or '')[:2000],
                    'to': (to_name or '')[:2000],
                    'cc': (cc_name or '')[:2000],
                    'date': date,
                    'direction': direction,
                    'source': name,
                })
        if not resp.get('has_more'):
            break
        cursor = resp['next_cursor']
    print(f'    {len(records)} records in Jan-Mar 2026', flush=True)
    return records


def count_existing():
    """Count records already in the consolidated database."""
    count = 0
    cursor = None
    while True:
        body = {'page_size': 100}
        if cursor:
            body['start_cursor'] = cursor
        resp = api_request('POST',
            f'https://api.notion.com/v1/data_sources/{CONSOLIDATED_DS_ID}/query', body)
        if not resp:
            break
        count += len(resp['results'])
        if not resp.get('has_more'):
            break
        cursor = resp['next_cursor']
    return count


def insert_one(rec):
    """Insert a single record. Returns True on success."""
    props = {
        'Subject': {'title': [{'type': 'text', 'text': {'content': rec['subject']}}]},
        'Direction': {'select': {'name': rec['direction']}},
        'Source': {'select': {'name': rec['source']}},
    }
    if rec['date']:
        props['Date'] = {'date': {'start': rec['date']}}
    for field, key in [('From', 'from'), ('To', 'to'), ('CC', 'cc')]:
        val = rec[key]
        if val:
            props[field] = {'rich_text': [{'type': 'text', 'text': {'content': val}}]}
        else:
            props[field] = {'rich_text': []}

    result = api_request('POST', 'https://api.notion.com/v1/pages', {
        'parent': {'type': 'data_source_id', 'data_source_id': CONSOLIDATED_DS_ID},
        'properties': props
    })
    return result and result.get('object') == 'page'


def main():
    print('=== FAST EMAIL CONSOLIDATION ===\n', flush=True)

    # Check how many already exist
    existing = count_existing()
    print(f'Already in consolidated DB: {existing} records\n', flush=True)

    # Fetch all sources
    print('Fetching all sources...', flush=True)
    all_records = []
    for ds_id, name in SENT_SOURCES:
        all_records.extend(fetch_source(ds_id, name, 'Sent'))
    for ds_id, name in INBOX_SOURCES:
        all_records.extend(fetch_source(ds_id, name, 'Inbox'))

    print(f'\nTotal in range: {len(all_records)}', flush=True)
    sent = sum(1 for r in all_records if r['direction'] == 'Sent')
    inbox = sum(1 for r in all_records if r['direction'] == 'Inbox')
    print(f'  Sent: {sent}, Inbox: {inbox}', flush=True)

    # Skip already-inserted records
    to_insert = all_records[existing:]
    print(f'  Skipping first {existing} (already inserted)', flush=True)
    print(f'  Remaining to insert: {len(to_insert)}\n', flush=True)

    if not to_insert:
        print('Nothing to insert!')
        return

    # Insert with thread pool (2 workers to stay under rate limit)
    inserted = 0
    errors = 0
    start = time.time()
    WORKERS = 2

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {}
        batch_idx = 0

        for i, rec in enumerate(to_insert):
            # Submit work
            f = pool.submit(insert_one, rec)
            futures[f] = i

            # Pace: ~2.5 req/sec total across workers
            time.sleep(0.15)

            # Collect completed futures periodically
            done = [f for f in futures if f.done()]
            for f in done:
                if f.result():
                    inserted += 1
                else:
                    errors += 1
                del futures[f]

            if (i + 1) % 200 == 0:
                elapsed = time.time() - start
                rate = (i + 1) / elapsed
                remaining = (len(to_insert) - i - 1) / rate
                print(f'  {i+1}/{len(to_insert)} submitted '
                      f'({inserted} ok, {errors} err) '
                      f'{rate:.1f}/s ~{remaining:.0f}s left', flush=True)

        # Wait for remaining
        for f in as_completed(futures):
            if f.result():
                inserted += 1
            else:
                errors += 1

    elapsed = time.time() - start
    print(f'\n=== COMPLETE ===', flush=True)
    print(f'Inserted: {inserted}', flush=True)
    print(f'Errors: {errors}', flush=True)
    print(f'Rate: {(inserted+errors)/elapsed:.1f} rec/s', flush=True)
    print(f'Time: {elapsed:.0f}s ({elapsed/60:.1f}m)', flush=True)


if __name__ == '__main__':
    main()
