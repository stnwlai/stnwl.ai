#!/usr/bin/env python3
"""
Notion Email Date Repair Script
Populates the Date field on DS1 (Work Email Archive — Sent) by parsing
the mangled Sent Time rich_text values. Falls back to page created_time.
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
DS1_ID = os.environ.get('NOTION_EMAIL_SOURCE_DS', 'YOUR_EMAIL_SOURCE_DATASOURCE_ID')

# Date parsing patterns for the Sent Time field
DATE_PATTERNS = [
    # "1.12.26 - 9:31 a.m." or "12.29.25 - 5:23 PM"
    (r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})\s*-?\s*(\d{1,2}):(\d{2})\s*(a\.?m\.?|p\.?m\.?|AM|PM)?',
     'full_datetime'),
    # "Sent Time - 1.12.26 - 4:44 p.m." (prefixed)
    (r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})\s*-\s*(\d{1,2}):(\d{2})\s*(a\.?m\.?|p\.?m\.?|AM|PM)?',
     'full_datetime'),
    # Just date "1.12.26" without time
    (r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})', 'date_only'),
]


def parse_date(sent_time_text):
    """Try to extract a date from the Sent Time rich_text value."""
    if not sent_time_text:
        return None

    # Try full datetime pattern first
    m = re.search(
        r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})\s*[-,]?\s*(\d{1,2}):(\d{2})\s*(a\.?m\.?|p\.?m\.?|AM|PM)?',
        sent_time_text
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
            dt = datetime(year, month, day, hour, minute)
            return dt.strftime('%Y-%m-%dT%H:%M:00.000+00:00')
        except ValueError:
            pass

    # Try date-only pattern
    m = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})', sent_time_text)
    if m:
        month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 2000
        try:
            dt = datetime(year, month, day)
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            pass

    return None


def api_request(method, url, data=None, retries=3):
    """Make Notion API request with retry logic."""
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
                print(f'  Rate limited, waiting {retry_after}s...')
                time.sleep(retry_after)
                continue
            elif e.code >= 500:
                time.sleep(2 ** attempt)
                continue
            else:
                print(f'  HTTP {e.code}: {body[:200]}')
                return None
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            print(f'  Error: {e}')
            return None
    return None


def update_page_date(page_id, date_value):
    """Update a page's Date property."""
    data = {
        'properties': {
            'Date': {
                'date': {
                    'start': date_value
                }
            }
        }
    }
    return api_request('PATCH', f'https://api.notion.com/v1/pages/{page_id}', data)


def main():
    print('=== NOTION EMAIL DATE REPAIR ===')
    print(f'Target: DS1 ({DS1_ID})')
    print()

    # Phase 1: Fetch all pages
    print('Phase 1: Fetching all DS1 pages...')
    all_pages = []
    cursor = None
    while True:
        body = {'page_size': 100}
        if cursor:
            body['start_cursor'] = cursor
        resp = api_request('POST',
            f'https://api.notion.com/v1/data_sources/{DS1_ID}/query', body)
        if not resp:
            print('ERROR: Failed to query data source')
            sys.exit(1)
        all_pages.extend(resp['results'])
        print(f'  Fetched {len(all_pages)} pages...')
        if not resp.get('has_more'):
            break
        cursor = resp['next_cursor']

    print(f'  Total: {len(all_pages)} pages')
    print()

    # Phase 2: Parse dates and categorize
    print('Phase 2: Parsing dates...')
    parsed = 0
    fallback = 0
    pages_to_update = []

    for page in all_pages:
        page_id = page['id']
        props = page['properties']

        # Check if Date is already set
        existing_date = props.get('Date', {})
        if existing_date.get('type') == 'date' and existing_date.get('date'):
            continue  # Already has a date

        # Try parsing Sent Time
        sent_time_rt = props.get('Sent Time', {}).get('rich_text', [])
        sent_time_text = ''.join(x['plain_text'] for x in sent_time_rt)

        date_val = parse_date(sent_time_text)
        if date_val:
            parsed += 1
            pages_to_update.append((page_id, date_val, 'parsed'))
        else:
            # Fallback to page created_time
            created = page.get('created_time', '')
            if created:
                # Use created_time as-is (ISO format)
                date_val = created[:19] + '.000+00:00'
                fallback += 1
                pages_to_update.append((page_id, date_val, 'fallback'))

    print(f'  Parsed from Sent Time: {parsed}')
    print(f'  Fallback to created_time: {fallback}')
    print(f'  Total to update: {len(pages_to_update)}')
    print()

    # Phase 3: Update pages
    print('Phase 3: Updating pages...')
    updated = 0
    errors = 0
    batch_start = time.time()

    for i, (page_id, date_val, source) in enumerate(pages_to_update):
        result = update_page_date(page_id, date_val)
        if result and result.get('object') == 'page':
            updated += 1
        else:
            errors += 1

        # Progress every 50
        if (i + 1) % 50 == 0:
            elapsed = time.time() - batch_start
            rate = (i + 1) / elapsed
            remaining = (len(pages_to_update) - i - 1) / rate if rate > 0 else 0
            print(f'  Updated {i+1}/{len(pages_to_update)} '
                  f'({updated} ok, {errors} err) '
                  f'~{remaining:.0f}s remaining')

        # Rate limiting: ~3 requests/sec to stay under Notion's limit
        time.sleep(0.35)

    print()
    print(f'=== COMPLETE ===')
    print(f'Updated: {updated}')
    print(f'Errors: {errors}')
    print(f'Total time: {time.time() - batch_start:.0f}s')


if __name__ == '__main__':
    main()
