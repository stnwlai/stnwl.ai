#!/usr/bin/env python3
"""
Notion Email Body Update — Stonewall Legal Intelligence Platform
=================================================
Reads consolidated_emails.json (with body text) and updates
existing Notion email pages with the body content as page blocks.

Usage:
  NOTION_TOKEN=ntn_xxx python3 scripts/notion_email_body_update.py
  NOTION_TOKEN=ntn_xxx python3 scripts/notion_email_body_update.py --dry-run
  NOTION_TOKEN=ntn_xxx python3 scripts/notion_email_body_update.py --limit 50
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

TOKEN = os.environ.get('NOTION_TOKEN', '')
API_VERSION = '2022-06-28'

# Consolidated email database
DB_ID = os.environ.get('NOTION_CONSOLIDATED_EMAIL_DB', '')

# Consolidated emails JSON path
EMAILS_JSON = os.path.join(os.path.dirname(__file__), '..', 'sources', 'emails', 'consolidated_emails.json')


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
            resp = urllib.request.urlopen(req, timeout=30)
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


def fetch_all_pages():
    """Fetch all pages from the consolidated email database."""
    print('Fetching existing Notion pages...')
    pages = []
    cursor = None
    while True:
        body = {'page_size': 100}
        if cursor:
            body['start_cursor'] = cursor
        resp = api_request('POST', f'https://api.notion.com/v1/databases/{DB_ID}/query', body)
        if not resp:
            print('  ERROR fetching pages')
            break
        pages.extend(resp.get('results', []))
        if not resp.get('has_more'):
            break
        cursor = resp['next_cursor']
        if len(pages) % 500 == 0:
            print(f'  {len(pages)} pages fetched...')
    print(f'  Total: {len(pages)} pages')
    return pages


def get_page_subject(page):
    """Extract subject from page properties."""
    props = page.get('properties', {})
    for key in ['Subject', '\ufeffSubject', 'Name']:
        prop = props.get(key, {})
        t = prop.get('type', '')
        if t == 'title':
            return ''.join(x['plain_text'] for x in prop.get('title', []))
    return ''


def get_page_date(page):
    """Extract date string from page."""
    props = page.get('properties', {})
    date_prop = props.get('Date', {})
    if date_prop.get('type') == 'date' and date_prop.get('date'):
        return date_prop['date']['start'][:10]
    return ''


def check_page_has_content(page_id):
    """Check if page already has block children (body content)."""
    resp = api_request('GET', f'https://api.notion.com/v1/blocks/{page_id}/children?page_size=1')
    if resp and resp.get('results'):
        return len(resp['results']) > 0
    return False


def text_to_blocks(text, max_chars=1900):
    """Split body text into Notion paragraph blocks (max 2000 chars per rich_text)."""
    if not text or not text.strip():
        return []

    blocks = []
    # Split by paragraphs first
    paragraphs = text.split('\n\n')

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # If paragraph fits in one block, use it directly
        if len(para) <= max_chars:
            blocks.append({
                'object': 'block',
                'type': 'paragraph',
                'paragraph': {
                    'rich_text': [{'type': 'text', 'text': {'content': para}}]
                }
            })
        else:
            # Split long paragraphs into chunks
            for i in range(0, len(para), max_chars):
                chunk = para[i:i + max_chars]
                blocks.append({
                    'object': 'block',
                    'type': 'paragraph',
                    'paragraph': {
                        'rich_text': [{'type': 'text', 'text': {'content': chunk}}]
                    }
                })

    return blocks


def append_body_to_page(page_id, body_text):
    """Append body text as blocks to a Notion page."""
    blocks = text_to_blocks(body_text)
    if not blocks:
        return False

    # Notion allows max 100 blocks per append
    for i in range(0, len(blocks), 100):
        batch = blocks[i:i + 100]
        resp = api_request('PATCH',
            f'https://api.notion.com/v1/blocks/{page_id}/children',
            {'children': batch}
        )
        if not resp:
            return False
    return True


def match_key(subject, date):
    """Create matching key from subject + date."""
    subj = (subject or '').lower().replace('\u200b', '').strip()[:120]
    return f"{subj}|||{(date or '')[:10]}"


def run():
    args = set(sys.argv[1:])
    dry_run = '--dry-run' in args
    limit = None
    for a in args:
        if a.startswith('--limit'):
            try:
                limit = int(a.split('=')[1] if '=' in a else sys.argv[sys.argv.index(a) + 1])
            except (ValueError, IndexError):
                limit = 50

    if not TOKEN:
        print('ERROR: NOTION_TOKEN not set')
        sys.exit(1)

    # Load consolidated emails
    print(f'Loading {EMAILS_JSON}...')
    with open(EMAILS_JSON) as f:
        emails = json.load(f)
    print(f'  {len(emails)} emails loaded')

    emails_with_body = [e for e in emails if e.get('body') and len(e['body'].strip()) > 10]
    print(f'  {len(emails_with_body)} have body text')

    # Build lookup by subject+date
    email_lookup = {}
    for e in emails_with_body:
        key = match_key(e['subject'], e.get('dateShort', ''))
        if key not in email_lookup:
            email_lookup[key] = e

    # Fetch Notion pages
    pages = fetch_all_pages()

    # Match and update
    matched = 0
    updated = 0
    skipped_has_content = 0
    no_body = 0
    errors = 0

    for i, page in enumerate(pages):
        if limit and updated >= limit:
            print(f'\n  Reached limit of {limit} updates')
            break

        subject = get_page_subject(page)
        date = get_page_date(page)
        key = match_key(subject, date)

        email = email_lookup.get(key)
        if not email:
            no_body += 1
            continue

        matched += 1
        page_id = page['id']

        # Check if page already has content
        if check_page_has_content(page_id):
            skipped_has_content += 1
            continue

        if dry_run:
            print(f'  [DRY RUN] Would update: {subject[:60]}')
            updated += 1
            continue

        # Append body
        body = email['body']
        success = append_body_to_page(page_id, body)
        if success:
            updated += 1
            if updated % 25 == 0:
                print(f'  {updated} pages updated...')
        else:
            errors += 1
            print(f'  ERROR updating: {subject[:60]}')

        # Rate limit: ~3 requests per second
        time.sleep(0.35)

    print(f'\n=== RESULTS ===')
    print(f'Total Notion pages: {len(pages)}')
    print(f'Matched to emails with body: {matched}')
    print(f'Updated with body content: {updated}')
    print(f'Skipped (already has content): {skipped_has_content}')
    print(f'No matching body found: {no_body}')
    print(f'Errors: {errors}')


if __name__ == '__main__':
    run()
