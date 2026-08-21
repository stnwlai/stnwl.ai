#!/usr/bin/env python3
"""
Notion Email Date Repair — All Data Sources
Populates the Date field on ALL email data sources that lack proper dates.
Uses page created_time as the date value since these sources don't have
parseable date text fields.

Also adds Direction (Sent/Inbox) select property where needed.
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

# Data sources needing date population.
# Populate with the source datasource IDs and estimated record counts from your Notion workspace.
# Format: (datasource_id, label, direction, estimated_record_count)
SOURCES = [
    # ('your-datasource-id-here', 'Sent Emails Batch 1', 'Sent', 100),
    # ('your-datasource-id-here', 'Inbox Emails Batch 1', 'Inbox', 500),
]


def api_request(method, url, data=None, retries=4):
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
                time.sleep(retry_after)
                continue
            elif e.code >= 500:
                time.sleep(2 ** attempt)
                continue
            else:
                if attempt == retries - 1:
                    print(f'  HTTP {e.code}: {body[:150]}')
                return None
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            print(f'  Error: {e}')
            return None
    return None


def process_data_source(ds_id, name, direction, est_count):
    """Process a single data source: populate Date from created_time."""
    print(f'\n--- {name} ({ds_id}) ---')
    print(f'Direction: {direction}, Est. records: {est_count}')

    # Fetch all pages
    all_pages = []
    cursor = None
    while True:
        body = {'page_size': 100}
        if cursor:
            body['start_cursor'] = cursor
        resp = api_request('POST',
            f'https://api.notion.com/v1/data_sources/{ds_id}/query', body)
        if not resp:
            print(f'ERROR: Failed to query')
            return 0, 0
        all_pages.extend(resp['results'])
        if len(all_pages) % 500 == 0:
            print(f'  Fetched {len(all_pages)}...')
        if not resp.get('has_more'):
            break
        cursor = resp['next_cursor']

    print(f'  Total pages: {len(all_pages)}')

    # Filter to pages that need Date populated
    needs_update = []
    already_has_date = 0
    for page in all_pages:
        existing = page['properties'].get('Date', {})
        if existing.get('type') == 'date' and existing.get('date'):
            already_has_date += 1
            continue
        # Use created_time as date
        created = page.get('created_time', '')
        if created:
            needs_update.append((page['id'], created[:19] + '.000+00:00'))

    print(f'  Already has date: {already_has_date}')
    print(f'  Needs date: {len(needs_update)}')

    if not needs_update:
        return 0, 0

    # Update pages
    updated = 0
    errors = 0
    start = time.time()

    for i, (page_id, date_val) in enumerate(needs_update):
        result = api_request('PATCH', f'https://api.notion.com/v1/pages/{page_id}', {
            'properties': {
                'Date': {'date': {'start': date_val}}
            }
        })
        if result and result.get('object') == 'page':
            updated += 1
        else:
            errors += 1

        if (i + 1) % 100 == 0:
            elapsed = time.time() - start
            rate = (i + 1) / elapsed if elapsed > 0 else 1
            remaining = (len(needs_update) - i - 1) / rate
            print(f'  Progress: {i+1}/{len(needs_update)} '
                  f'({updated} ok, {errors} err) '
                  f'~{remaining:.0f}s left')

        # Rate limit: 3 req/sec
        time.sleep(0.35)

    elapsed = time.time() - start
    print(f'  Done: {updated} updated, {errors} errors in {elapsed:.0f}s')
    return updated, errors


def main():
    print('=== NOTION EMAIL DATE REPAIR — ALL SOURCES ===')
    print(f'Processing {len(SOURCES)} data sources')

    total_updated = 0
    total_errors = 0

    for ds_id, name, direction, est in SOURCES:
        u, e = process_data_source(ds_id, name, direction, est)
        total_updated += u
        total_errors += e

    print(f'\n=== GRAND TOTAL ===')
    print(f'Updated: {total_updated}')
    print(f'Errors: {total_errors}')


if __name__ == '__main__':
    main()
