#!/usr/bin/env python3
"""
Batch Email → Case Wiring Script
Processes N emails per run with offset tracking.
Run repeatedly until all are processed.
"""

import json, os, re, sys, time, urllib.request, urllib.error

TOKEN = os.environ.get('NOTION_TOKEN', '')
LEGAL_MATTERS_DB = os.environ.get('NOTION_LEGAL_MATTERS_DB', 'YOUR_LEGAL_MATTERS_DATABASE_ID')
ALL_EMAIL_DB = os.environ.get('NOTION_ALL_EMAIL_DB', 'YOUR_ALL_EMAIL_DATABASE_ID')
BATCH_SIZE = int(os.environ.get('BATCH_SIZE', '200'))
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wire_state.json')

AMBIGUOUS_KEYWORDS = {'alpha', 'beta', 'gamma', 'delta', 'sample', 'matter'}

def api(method, endpoint, data=None, retries=3):
    url = f'https://api.notion.com/v1/{endpoint}'
    for attempt in range(retries):
        try:
            body = json.dumps(data).encode() if data else None
            req = urllib.request.Request(url, data=body, headers={
                'Authorization': f'Bearer {TOKEN}',
                'Notion-Version': '2022-06-28',
                'Content-Type': 'application/json'
            }, method=method)
            return json.loads(urllib.request.urlopen(req).read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(float(e.headers.get('Retry-After', 2)))
                continue
            raise
    raise RuntimeError('Retries exhausted')

def get_all_pages(db_id):
    pages, cursor = [], None
    while True:
        body = {'page_size': 100}
        if cursor: body['start_cursor'] = cursor
        r = api('POST', f'databases/{db_id}/query', body)
        pages.extend(r.get('results', []))
        if not r.get('has_more'): break
        cursor = r.get('next_cursor')
        time.sleep(0.35)
    return pages

def load_cases():
    cases_raw = get_all_pages(LEGAL_MATTERS_DB)
    matchers = []
    for c in cases_raw:
        p = c.get('properties', {})
        name = ''.join(t.get('plain_text','') for t in p.get('Case Name',{}).get('title',[]))
        claim = ''.join(t.get('plain_text','') for t in p.get('Claim Number',{}).get('rich_text',[]))
        
        keywords = set()
        parts = re.split(r'\s+v\.?\s+', name, maxsplit=1)
        if parts:
            for pl in parts[0].split('/'):
                pl = re.sub(r'\s*\(.*?\)', '', pl).strip()
                if pl and len(pl) > 2: keywords.add(pl.lower())
        if len(parts) > 1:
            for ap in parts[1].split('&')[1:]:
                ap = re.sub(r'\s*\(.*?\)', '', ap).strip()
                if ap and len(ap) > 2 and ap.lower() not in ('carrier', 'logistics co', 'sample account'):
                    keywords.add(ap.lower())
        
        regex = re.compile('|'.join(re.escape(k) for k in sorted(keywords, key=len, reverse=True)), re.I) if keywords else None
        claims = set()
        if claim:
            claims.add(claim.strip().lower())
            claims.add(re.sub(r'[-\s]','', claim.strip()).lower())
        
        matchers.append({'id': c['id'], 'name': name, 'keywords': keywords, 'regex': regex, 'claims': claims})
    return matchers

def match(subject, matchers):
    if not subject: return []
    sl = subject.lower()
    sc = re.sub(r'[-\s]','', sl)
    hits = []
    for m in matchers:
        for cl in m['claims']:
            if cl in sl or re.sub(r'[-\s]','',cl) in sc:
                hits.append(m['id']); break
        else:
            if m['regex'] and m['regex'].search(subject):
                found = m['regex'].findall(subject)
                if any(len(f)>3 for f in found):
                    all_amb = all(f.lower() in AMBIGUOUS_KEYWORDS for f in found)
                    if all_amb:
                        if any(mk in sl for mk in ['v.', ' v ', 'cl#', 'claim', 'depo', 'mediation', 'settlement']):
                            hits.append(m['id'])
                    else:
                        hits.append(m['id'])
    return list(set(hits))

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f: return json.load(f)
    return {'processed': set(), 'matched': 0, 'skipped': 0, 'already_linked': 0}

def save_state(state):
    state_copy = dict(state)
    state_copy['processed'] = list(state_copy['processed'])
    with open(STATE_FILE, 'w') as f: json.dump(state_copy, f)

def main():
    print(f'Loading cases...')
    matchers = load_cases()
    print(f'  {len(matchers)} cases loaded')
    
    state = load_state()
    if isinstance(state['processed'], list): state['processed'] = set(state['processed'])
    
    print(f'Loading emails...')
    emails = get_all_pages(ALL_EMAIL_DB)
    print(f'  {len(emails)} total emails, {len(state["processed"])} already processed')
    
    batch_matched = 0
    batch_processed = 0
    
    for email in emails:
        if batch_processed >= BATCH_SIZE:
            break
        
        pid = email['id']
        if pid in state['processed']:
            continue
        
        props = email.get('properties', {})
        subject = ''.join(t.get('plain_text','') for t in props.get('Subject',{}).get('title',[]))
        
        # Check existing relation
        rel = props.get('⚖️ Case', {})
        if rel.get('type') == 'relation' and rel.get('relation'):
            state['processed'].add(pid)
            state['already_linked'] += 1
            batch_processed += 1
            continue
        
        case_ids = match(subject, matchers)
        
        if case_ids:
            try:
                api('PATCH', f'pages/{pid}', {
                    'properties': {'⚖️ Case': {'relation': [{'id': case_ids[0]}]}}
                })
                batch_matched += 1
                state['matched'] += 1
                time.sleep(0.35)
            except Exception as e:
                print(f'  Error: {str(e)[:80]}')
        else:
            state['skipped'] += 1
        
        state['processed'].add(pid)
        batch_processed += 1
        
        if batch_processed % 50 == 0:
            print(f'  Progress: {batch_processed}/{BATCH_SIZE} this batch, {batch_matched} matched')
    
    save_state(state)
    remaining = len(emails) - len(state['processed'])
    print(f'\n═══ BATCH COMPLETE ═══')
    print(f'  This batch: {batch_processed} processed, {batch_matched} matched')
    print(f'  Cumulative: {state["matched"]} matched, {state["skipped"]} unmatched, {state["already_linked"]} already linked')
    print(f'  Remaining: {remaining}')
    if remaining > 0:
        print(f'  Run again to process next batch.')
    else:
        print(f'  ✓ ALL EMAILS PROCESSED')

if __name__ == '__main__':
    main()
