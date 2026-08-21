#!/usr/bin/env python3
"""
Notion Case Wiring Script — Stonewall Legal Intelligence Platform
==================================================
Phase 1: Add a RELATION field "⚖️ Case" to the consolidated email DB
         pointing to Legal Matters.
Phase 2: Scan all emails, match by subject line to case names/claim numbers,
         and set the relation.
Phase 3: Add rollup fields on Legal Matters for email counts.

Usage:
  NOTION_TOKEN=ntn_xxx python3 notion_wire_cases.py

Environment Variables:
  NOTION_TOKEN  - Notion integration token (required)
  DRY_RUN       - Set to "1" to preview matches without writing (optional)
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

# Database IDs — set via environment variables or update below for your workspace
LEGAL_MATTERS_DB = os.environ.get('NOTION_LEGAL_MATTERS_DB', 'YOUR_LEGAL_MATTERS_DATABASE_ID')
ALL_EMAIL_DB = os.environ.get('NOTION_ALL_EMAIL_DB', 'YOUR_ALL_EMAIL_DATABASE_ID')
EMAIL_LEGACY_DB = os.environ.get('NOTION_EMAIL_LEGACY_DB', 'YOUR_EMAIL_LEGACY_DATABASE_ID')
WORKFLOW_EVENTS_DB = os.environ.get('NOTION_EVENTS_DB', 'YOUR_EVENTS_DATABASE_ID')
STONEWALL_ARCHIVE_DB = os.environ.get('NOTION_ARCHIVE_DB', 'YOUR_ARCHIVE_DATABASE_ID')

# ── API Helper ──────────────────────────────────────────────────────────────
def api(method, endpoint, data=None, retries=4):
    """Make a Notion API request with retry logic."""
    url = f'https://api.notion.com/v1/{endpoint}'
    for attempt in range(retries):
        try:
            body = json.dumps(data).encode() if data else None
            req = urllib.request.Request(url, data=body, headers={
                'Authorization': f'Bearer {TOKEN}',
                'Notion-Version': API_VERSION,
                'Content-Type': 'application/json'
            }, method=method)
            resp = urllib.request.urlopen(req)
            return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body_text = e.read().decode() if e.fp else ''
            if e.code == 429:
                wait = float(e.headers.get('Retry-After', 2 * (attempt + 1)))
                print(f'  Rate limited. Waiting {wait}s...')
                time.sleep(wait)
                continue
            elif e.code == 409 and attempt < retries - 1:
                print(f'  Conflict (409). Retrying in 2s...')
                time.sleep(2)
                continue
            else:
                print(f'  API Error {e.code}: {body_text[:300]}')
                raise
    raise RuntimeError(f'Failed after {retries} retries: {method} {endpoint}')


def paginate_db(db_id, filter_obj=None, page_size=100):
    """Fetch all pages from a Notion database."""
    pages = []
    cursor = None
    while True:
        body = {'page_size': page_size}
        if filter_obj:
            body['filter'] = filter_obj
        if cursor:
            body['start_cursor'] = cursor
        result = api('POST', f'databases/{db_id}/query', body)
        pages.extend(result.get('results', []))
        if not result.get('has_more'):
            break
        cursor = result.get('next_cursor')
        time.sleep(0.35)
    return pages


# ── Case Matching Engine ────────────────────────────────────────────────────
def build_case_matchers(cases):
    """
    Build regex patterns and keyword sets for matching email subjects to cases.
    Returns list of (case_id, case_name, compiled_regex, claim_numbers).
    """
    matchers = []
    for c in cases:
        name = c['name']
        case_id = c['id']
        claim = c.get('claim', '')
        
        # Extract the plaintiff surname(s) from case name
        # Format is typically "Surname v. Carrier & Driver" or "Surname/Surname v. ..."
        keywords = set()
        
        # Get everything before " v. " or " v "
        parts = re.split(r'\s+v\.?\s+', name, maxsplit=1)
        if parts:
            plaintiff_part = parts[0].strip()
            # Split on / for multi-plaintiff
            for p in plaintiff_part.split('/'):
                p = p.strip()
                # Remove parenthetical qualifiers
                p = re.sub(r'\s*\(.*?\)\s*', '', p)
                if p and len(p) > 2:
                    keywords.add(p.lower())
        
        # Also extract driver/defendant surnames after "&"
        if len(parts) > 1:
            def_part = parts[1]
            amp_parts = def_part.split('&')
            for ap in amp_parts[1:]:  # skip the lead carrier defendant
                ap = ap.strip()
                ap = re.sub(r'\s*\(.*?\)\s*', '', ap)
                if ap and len(ap) > 2 and ap.lower() not in ('carrier', 'logistics co', 'sample account'):
                    keywords.add(ap.lower())
        
        # Build regex from keywords
        if keywords:
            # Sort longest first for greedy matching
            kw_list = sorted(keywords, key=len, reverse=True)
            pattern = '|'.join(re.escape(k) for k in kw_list)
            regex = re.compile(pattern, re.IGNORECASE)
        else:
            regex = None
        
        # Claim number patterns
        claims = set()
        if claim:
            # Normalize claim number
            clean = claim.strip()
            if clean:
                claims.add(clean.lower())
                # Also try without dashes/spaces
                claims.add(re.sub(r'[-\s]', '', clean).lower())
        
        matchers.append({
            'id': case_id,
            'name': name,
            'keywords': keywords,
            'regex': regex,
            'claims': claims
        })
    
    return matchers


def match_subject_to_case(subject, matchers):
    """
    Match an email subject to a case. Returns list of matching case IDs.
    Prioritizes claim number matches, then keyword matches.
    """
    if not subject:
        return []
    
    subject_lower = subject.lower()
    subject_clean = re.sub(r'[-\s]', '', subject_lower)
    matches = []
    
    # Common words that happen to be case names — require claim number or "v." context
    AMBIGUOUS_KEYWORDS = {'alpha', 'beta', 'gamma', 'delta', 'sample', 'matter'}
    
    for m in matchers:
        # Claim number match (highest confidence)
        for cl in m['claims']:
            if cl in subject_lower or re.sub(r'[-\s]', '', cl) in subject_clean:
                matches.append(m['id'])
                break
        else:
            # Keyword/regex match
            if m['regex'] and m['regex'].search(subject):
                found = m['regex'].findall(subject)
                if any(len(f) > 3 for f in found):
                    # Check if ALL matches are ambiguous common words
                    all_ambiguous = all(f.lower() in AMBIGUOUS_KEYWORDS for f in found)
                    if all_ambiguous:
                        # Require legal context: "v.", "CL#", claim-number prefix
                        has_context = any(marker in subject_lower for marker in 
                                         ['v.', ' v ', 'cl#', 'cl ', 'claim', 'depo', 'mediation', 
                                          'settlement', 'discovery', 'hearing', 'motion'])
                        if has_context:
                            matches.append(m['id'])
                    else:
                        matches.append(m['id'])
    
    return list(set(matches))


# ── Phase 1: Check/Create Relation Field ────────────────────────────────────
def ensure_case_relation(db_id, db_name):
    """
    Check if a '⚖️ Case' relation field exists on the given DB.
    If not, create it pointing to Legal Matters.
    Returns the property name.
    """
    prop_name = '⚖️ Case'
    
    # Get current schema
    db = api('GET', f'databases/{db_id}')
    props = db.get('properties', {})
    
    if prop_name in props:
        existing = props[prop_name]
        if existing.get('type') == 'relation':
            print(f'  ✓ {db_name} already has "{prop_name}" relation field')
            return prop_name
        else:
            print(f'  ⚠ {db_name} has "{prop_name}" but type is {existing.get("type")}, not relation')
            prop_name = '⚖️ Case Link'  # Use alternate name
    
    if DRY_RUN:
        print(f'  [DRY RUN] Would create "{prop_name}" relation on {db_name}')
        return prop_name
    
    # Create the relation property
    print(f'  Creating "{prop_name}" relation on {db_name} → Legal Matters...')
    update = {
        'properties': {
            prop_name: {
                'relation': {
                    'database_id': LEGAL_MATTERS_DB,
                    'single_property': {}
                }
            }
        }
    }
    api('PATCH', f'databases/{db_id}', update)
    print(f'  ✓ Created "{prop_name}" relation')
    time.sleep(1)
    return prop_name


# ── Phase 2: Wire Emails to Cases ──────────────────────────────────────────
def wire_emails_to_cases(email_db_id, db_name, matchers, relation_prop):
    """Scan all emails and set the Case relation based on subject matching."""
    print(f'\n  Scanning {db_name} emails...')
    emails = paginate_db(email_db_id)
    print(f'  Found {len(emails)} emails')
    
    matched = 0
    unmatched = 0
    errors = 0
    
    for i, email in enumerate(emails):
        props = email.get('properties', {})
        page_id = email['id']
        
        # Get subject
        subject_prop = props.get('Subject', {})
        subject = ''
        if subject_prop.get('type') == 'title':
            subject = ''.join(t.get('plain_text', '') for t in subject_prop.get('title', []))
        
        if not subject:
            unmatched += 1
            continue
        
        # Check if already has a case relation set
        existing_rel = props.get(relation_prop, {})
        if existing_rel.get('type') == 'relation' and existing_rel.get('relation'):
            # Already linked
            continue
        
        # Match
        case_ids = match_subject_to_case(subject, matchers)
        
        if not case_ids:
            unmatched += 1
            continue
        
        if DRY_RUN:
            case_names = [m['name'] for m in matchers if m['id'] in case_ids]
            print(f'    [DRY RUN] "{subject[:60]}" → {case_names}')
            matched += 1
            continue
        
        # Set the relation
        try:
            relation_value = [{'id': cid} for cid in case_ids[:1]]  # Limit to first match
            api('PATCH', f'pages/{page_id}', {
                'properties': {
                    relation_prop: {
                        'relation': relation_value
                    }
                }
            })
            matched += 1
            if matched % 25 == 0:
                print(f'    Linked {matched} emails so far...')
            time.sleep(0.35)
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f'    Error on "{subject[:40]}": {e}')
    
    print(f'  ✓ {db_name}: {matched} linked, {unmatched} unmatched, {errors} errors')
    return matched, unmatched


# ── Phase 3: Wire Legacy Email DB ──────────────────────────────────────────
def wire_legacy_emails(matchers, relation_prop):
    """
    The Legacy Email DB uses multi_select Case tags. We can also add the
    relation field and wire it up, using both the existing tags AND subject matching.
    """
    print(f'\n  Scanning Legacy Email Correspondence...')
    emails = paginate_db(EMAIL_LEGACY_DB)
    print(f'  Found {len(emails)} legacy emails')
    
    # Build a quick lookup: tag name → case ID
    tag_to_case = {}
    for m in matchers:
        # Extract short name from case name
        short = m['name'].split(' v.')[0].split(' v ')[0].strip()
        tag_to_case[short.lower()] = m['id']
        # Also map by first word only
        first_word = short.split()[0].lower() if short else ''
        if first_word and len(first_word) > 3:
            tag_to_case[first_word] = m['id']
    
    matched = 0
    for email in emails:
        props = email.get('properties', {})
        page_id = email['id']
        
        # Check existing case tags
        case_tags = [o.get('name', '') for o in props.get('Case', {}).get('multi_select', [])]
        
        # Check if relation already set
        existing_rel = props.get(relation_prop, {})
        if existing_rel.get('type') == 'relation' and existing_rel.get('relation'):
            continue
        
        # Try to match from tags first
        case_ids = []
        for tag in case_tags:
            tag_lower = tag.lower()
            if tag_lower in tag_to_case:
                case_ids.append(tag_to_case[tag_lower])
        
        # Fallback to subject matching
        if not case_ids:
            subject = ''.join(t.get('plain_text', '') for t in props.get('Subject', {}).get('title', []))
            case_ids = match_subject_to_case(subject, matchers)
        
        if case_ids:
            if not DRY_RUN:
                try:
                    api('PATCH', f'pages/{page_id}', {
                        'properties': {
                            relation_prop: {
                                'relation': [{'id': case_ids[0]}]
                            }
                        }
                    })
                    matched += 1
                    time.sleep(0.35)
                except Exception as e:
                    pass
            else:
                matched += 1
    
    print(f'  ✓ Legacy emails: {matched} linked')

# ── Phase 4: Wire Events ────────────────────────────────────────────────────
def wire_events(matchers):
    """
    Workflow events don't have a Case relation yet. Add one and try to match
    from event names and verbatim quotes.
    """
    prop_name = ensure_case_relation(WORKFLOW_EVENTS_DB, 'Events')
    
    events = paginate_db(WORKFLOW_EVENTS_DB)
    print(f'  Found {len(events)} events')
    
    matched = 0
    for event in events:
        props = event.get('properties', {})
        page_id = event['id']
        
        existing_rel = props.get(prop_name, {})
        if existing_rel.get('type') == 'relation' and existing_rel.get('relation'):
            continue
        
        # Try matching from event name
        name = ''.join(t.get('plain_text', '') for t in props.get('Event Name', {}).get('title', []))
        case_ids = match_subject_to_case(name, matchers)
        
        if case_ids and not DRY_RUN:
            try:
                api('PATCH', f'pages/{page_id}', {
                    'properties': {
                        prop_name: {'relation': [{'id': case_ids[0]}]}
                    }
                })
                matched += 1
                time.sleep(0.35)
            except:
                pass
    
    print(f'  ✓ Events: {matched} linked')


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    if not TOKEN:
        print('ERROR: Set NOTION_TOKEN environment variable')
        sys.exit(1)
    
    mode = 'DRY RUN' if DRY_RUN else 'LIVE'
    print(f'═══ Case Wiring Engine ({mode}) ═══')
    print(f'Time: {datetime.now().isoformat()}')
    print()
    
    # Step 1: Load all cases from Legal Matters
    print('Phase 0: Loading Legal Matters cases...')
    cases_raw = paginate_db(LEGAL_MATTERS_DB)
    cases = []
    for c in cases_raw:
        props = c.get('properties', {})
        name = ''.join(t.get('plain_text', '') for t in props.get('Case Name', {}).get('title', []))
        claim = ''.join(t.get('plain_text', '') for t in props.get('Claim Number', {}).get('rich_text', []))
        cases.append({'id': c['id'], 'name': name, 'claim': claim})
    print(f'  Loaded {len(cases)} cases')
    
    # Step 2: Build matchers
    print('\nPhase 0.5: Building case matchers...')
    matchers = build_case_matchers(cases)
    for m in matchers:
        print(f'  {m["name"][:40]:40} keywords={m["keywords"]}  claims={m["claims"]}')
    
    # Step 3: Ensure relation fields exist
    print('\n═══ Phase 1: Creating relation fields ═══')
    email_rel = ensure_case_relation(ALL_EMAIL_DB, 'All Email')
    legacy_rel = ensure_case_relation(EMAIL_LEGACY_DB, 'Email Legacy')
    
    # Step 4: Wire emails
    print('\n═══ Phase 2: Wiring emails to cases ═══')
    wire_emails_to_cases(ALL_EMAIL_DB, 'All Email', matchers, email_rel)
    
    # Step 5: Wire legacy emails
    print('\n═══ Phase 3: Wiring legacy emails ═══')
    wire_legacy_emails(matchers, legacy_rel)
    
    # Step 6: Wire events
    print('\n═══ Phase 4: Wiring events ═══')
    wire_events(matchers)
    
    print('\n═══ COMPLETE ═══')
    print('Next steps:')
    print('  1. Open Legal Matters in Notion — each case page now shows related emails')
    print('  2. Create a "By Case" view in All Email (group by Case relation)')
    print('  3. Add rollup on Legal Matters: Email Count, Latest Email Date')


if __name__ == '__main__':
    main()
