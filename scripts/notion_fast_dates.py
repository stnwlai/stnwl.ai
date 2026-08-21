#!/usr/bin/env python3
"""
Fast date population for all scattered data sources.
Uses threading and skips pages that already have dates.
"""

import json
import os
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

TOKEN = os.environ.get('NOTION_TOKEN', '')
API_VERSION = '2025-09-03'

# Populate with the source datasource IDs and estimated page counts from your Notion workspace.
# Format: (datasource_id, label, estimated_page_count)
SOURCES = [
    # ('your-datasource-id-here', 'Sent Emails Batch 1', 100),
    # ('your-datasource-id-here', 'Inbox Emails Batch 1', 500),
]


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
            return json.loads(urllib.request.urlopen(req).read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(float(e.headers.get('Retry-After', 1)) + 0.5)
                continue
            elif e.code >= 500:
                time.sleep(2 ** attempt)
                continue
            return None
        except Exception:
            if attempt < retries - 1:
                time.sleep(1)
                continue
            return None
    return None


def update_date(page_id, date_val):
    result = api_request('PATCH', f'https://api.notion.com/v1/pages/{page_id}', {
        'properties': {'Date': {'date': {'start': date_val}}}
    })
    return result and result.get('object') == 'page'


def process_source(ds_id, name, est):
    print(f'\n--- {name} ({est} est.) ---', flush=True)

    # Fetch all pages, filter to those needing dates
    needs_update = []
    cursor = None
    total = 0
    while True:
        body = {'page_size': 100}
        if cursor:
            body['start_cursor'] = cursor
        resp = api_request('POST',
            f'https://api.notion.com/v1/data_sources/{ds_id}/query', body)
        if not resp:
            break
        for page in resp['results']:
            total += 1
            existing = page['properties'].get('Date', {})
            if existing.get('type') == 'date' and existing.get('date'):
                continue  # Already has date
            created = page.get('created_time', '')
            if created:
                needs_update.append((page['id'], created[:19] + '.000+00:00'))
        if not resp.get('has_more'):
            break
        cursor = resp['next_cursor']

    already = total - len(needs_update)
    print(f'  Total: {total}, Already done: {already}, Need update: {len(needs_update)}', flush=True)

    if not needs_update:
        return 0, 0

    # Update with 2 threads
    inserted = 0
    errors = 0
    start = time.time()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {}
        for i, (pid, dval) in enumerate(needs_update):
            f = pool.submit(update_date, pid, dval)
            futures[f] = i
            time.sleep(0.15)

            done = [f for f in futures if f.done()]
            for f in done:
                if f.result():
                    inserted += 1
                else:
                    errors += 1
                del futures[f]

            if (i + 1) % 500 == 0:
                elapsed = time.time() - start
                rate = (i + 1) / elapsed
                remaining = (len(needs_update) - i - 1) / rate
                print(f'  {i+1}/{len(needs_update)} ({inserted} ok, {errors} err) '
                      f'{rate:.1f}/s ~{remaining:.0f}s left', flush=True)

        for f in as_completed(futures):
            if f.result():
                inserted += 1
            else:
                errors += 1

    elapsed = time.time() - start
    print(f'  Done: {inserted} ok, {errors} err in {elapsed:.0f}s', flush=True)
    return inserted, errors


def main():
    print('=== FAST DATE POPULATION — ALL SOURCES ===\n', flush=True)
    total_ok = 0
    total_err = 0

    for ds_id, name, est in SOURCES:
        ok, err = process_source(ds_id, name, est)
        total_ok += ok
        total_err += err

    print(f'\n=== GRAND TOTAL ===', flush=True)
    print(f'Updated: {total_ok}', flush=True)
    print(f'Errors: {total_err}', flush=True)


if __name__ == '__main__':
    main()
