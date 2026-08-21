#!/usr/bin/env python3
"""
Legal Matters PDF Generator — Stonewall Legal Intelligence Platform
=====================================================
Pulls the Legal Matters database from Notion and generates a styled
dashboard PDF with summary cards, grouped sections, and color coding.

Usage:
  NOTION_TOKEN=ntn_xxx python3 legal_matters_pdf.py
  NOTION_TOKEN=ntn_xxx python3 legal_matters_pdf.py -o ~/Desktop/legal_matters.pdf
  NOTION_TOKEN=ntn_xxx python3 legal_matters_pdf.py --html

Output: legal_matters.pdf (current directory by default)
"""

import html as html_mod
import json
import os
import sys
import time
import argparse
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

TOKEN = os.environ.get('NOTION_TOKEN', '')
API_VERSION = '2022-06-28'
LEGAL_MATTERS_DB = os.environ.get('NOTION_LEGAL_MATTERS_DB', 'YOUR_LEGAL_MATTERS_DATABASE_ID')

# ── Notion API ────────────────────────────────────────────────────────────────
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
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except urllib.error.HTTPError as e:
            body_text = e.read().decode() if e.fp else ''
            if e.code == 429:
                time.sleep(float(e.headers.get('Retry-After', 2 * (attempt + 1))))
                continue
            elif e.code >= 500 and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            print(f'API Error {e.code}: {body_text[:200]}')
            raise
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            if attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            raise
    raise RuntimeError(f'Failed: {method} {endpoint}')


def paginate_db(db_id, sorts=None):
    pages, cursor = [], None
    while True:
        body = {'page_size': 100}
        if cursor:
            body['start_cursor'] = cursor
        if sorts:
            body['sorts'] = sorts
        result = api('POST', f'databases/{db_id}/query', body)
        pages.extend(result.get('results', []))
        if not result.get('has_more'):
            break
        cursor = result.get('next_cursor')
        if not cursor:
            break
        time.sleep(0.3)
    return pages


# ── Property Extractors ───────────────────────────────────────────────────────
def get_title(props, key):
    return ''.join(t.get('plain_text', '') for t in props.get(key, {}).get('title', []))

def get_text(props, key):
    return ''.join(t.get('plain_text', '') for t in props.get(key, {}).get('rich_text', []))

def get_select(props, key):
    s = props.get(key, {}).get('select') or {}
    return s.get('name', '')

def get_date(props, key):
    d = props.get(key, {}).get('date') or {}
    start = d.get('start', '')
    return start[:10] if start else ''


# ── Data Extraction ───────────────────────────────────────────────────────────
def extract_case(page):
    props = page.get('properties', {})
    return {
        'name':       get_title(props, 'Case Name'),
        'claim':      get_text(props, 'Claim Number'),
        'status':     get_select(props, 'Status'),
        'phase':      get_select(props, 'Phase'),
        'plaintiff':  get_text(props, 'Plaintiff'),
        'oc_firm':    get_text(props, 'OC Firm'),
        'opp':        get_text(props, 'Opposing Counsel'),
        'adjuster':   get_text(props, 'Adjuster'),
        'driver':     get_text(props, 'Carrier Driver'),
        'injury':     get_text(props, 'Injury Type'),
        'mediation':  get_date(props, 'Mediation Date'),
        'trial':      get_date(props, 'Trial Date'),
        'cme':        get_date(props, 'CME Deadline'),
        'next_dl':    get_date(props, 'Next Deadline'),
    }


# ── Grouping & Sorting ───────────────────────────────────────────────────────
CLOSED_STATUSES = {'settled', 'closed', 'dismissed', 'resolved', 'inactive'}

def is_closed(case):
    return (case.get('status') or '').lower() in CLOSED_STATUSES

STATUS_ORDER = {
    'Trial':              0,
    'Trial Prep':         1,
    'Mediation':          2,
    'Discovery':          3,
    'Active':             4,
    'New Intake':         5,
    'Settlement':         6,
    '':                   7,
    'Settled':            10,
    'Closed':             11,
    'Dismissed':          12,
    'Resolved':           13,
    'Inactive':           14,
}

def sort_key(case):
    s = case.get('status', '')
    # Sort by next deadline within same status group
    dl = case.get('next_dl') or case.get('trial') or case.get('mediation') or 'zzzz'
    return (STATUS_ORDER.get(s, 7), dl, case.get('name', '').lower())


# ── Status Styling (Notion palette) ──────────────────────────────────────────
STATUS_THEME = {
    'Active':      {'fg': '#1d7a4c', 'bg': '#d3f1e0'},
    'Discovery':   {'fg': '#2a6495', 'bg': '#d3e5ef'},
    'Trial':       {'fg': '#9c2b2b', 'bg': '#ffe0e0'},
    'Trial Prep':  {'fg': '#994400', 'bg': '#ffe4c4'},
    'Mediation':   {'fg': '#7a5700', 'bg': '#fdecc8'},
    'New Intake':  {'fg': '#5b3fa0', 'bg': '#ede7f6'},
    'Settlement':  {'fg': '#0e6655', 'bg': '#d1f2eb'},
    'Settled':     {'fg': '#787774', 'bg': '#e3e2df'},
    'Closed':      {'fg': '#787774', 'bg': '#e3e2df'},
    'Dismissed':   {'fg': '#787774', 'bg': '#f0f0ee'},
    'Resolved':    {'fg': '#787774', 'bg': '#e3e2df'},
    'Inactive':    {'fg': '#aaa',    'bg': '#f5f5f3'},
}
DEFAULT_THEME = {'fg': '#37352f', 'bg': '#f1f0ee'}

def get_theme(status):
    return STATUS_THEME.get(status, DEFAULT_THEME)


# ── HTML Helpers ──────────────────────────────────────────────────────────────
def esc(v):
    return html_mod.escape(str(v)) if v else ''

def fmt_date(d):
    if not d:
        return '<span class="empty">—</span>'
    try:
        dt = datetime.strptime(d, '%Y-%m-%d')
        return dt.strftime('%m/%d/%y')
    except ValueError:
        return esc(d)

def fmt_empty(v):
    return esc(v) if v else '<span class="empty">—</span>'

def truncate(v, n=40):
    if not v:
        return ''
    return v[:n] + '…' if len(v) > n else v


# ── Summary Stats ─────────────────────────────────────────────────────────────
def compute_stats(cases):
    active = [c for c in cases if not is_closed(c)]
    closed = [c for c in cases if is_closed(c)]
    return {
        'total':           len(cases),
        'active_count':    len(active),
        'closed_count':    len(closed),
        'trial_count':     sum(1 for c in active if (c.get('status') or '').lower() in ('trial', 'trial prep')),
        'mediation_count': sum(1 for c in active if (c.get('status') or '').lower() == 'mediation'),
        'discovery_count': sum(1 for c in active if (c.get('status') or '').lower() == 'discovery'),
        'has_trial_date':  sum(1 for c in active if c.get('trial')),
        'has_mediation':   sum(1 for c in active if c.get('mediation')),
    }


# ── CSS ───────────────────────────────────────────────────────────────────────
CSS = """
@page {
    size: Letter landscape;
    margin: 0.45in 0.4in;
    @bottom-center {
        content: "Page " counter(page) " of " counter(pages);
        font-family: -apple-system, 'Segoe UI', sans-serif;
        font-size: 6pt;
        color: #9b9a97;
    }
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
    font-size: 7.5pt;
    color: #37352f;
    background: #ffffff;
}

/* ── Page Header ─────────────────────────────── */
.header {
    padding: 0 0 12pt 0;
    margin-bottom: 12pt;
    border-bottom: 1pt solid #e9e9e7;
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
}
.header-left h1 {
    font-size: 20pt;
    font-weight: 700;
    color: #37352f;
    letter-spacing: -0.02em;
    line-height: 1.1;
}
.header-left .icon {
    font-size: 14pt;
    margin-bottom: 2pt;
    display: block;
}
.header-left .sub {
    font-size: 7.5pt;
    color: #9b9a97;
    margin-top: 3pt;
}
.header-left .sub b { color: #37352f; font-weight: 600; }
.header-right {
    text-align: right;
    font-size: 6.5pt;
    color: #9b9a97;
}

/* ── Summary Cards ──────────────────────────── */
.cards {
    display: flex;
    gap: 6pt;
    margin-bottom: 14pt;
}
.card {
    flex: 1;
    background: #f7f6f3;
    border-radius: 5pt;
    padding: 7pt 8pt;
    text-align: center;
    border: 0.5pt solid #e9e9e7;
}
.card .num {
    font-size: 16pt;
    font-weight: 700;
    line-height: 1.1;
    color: #37352f;
}
.card .lbl {
    font-size: 5.5pt;
    text-transform: uppercase;
    letter-spacing: 0.09em;
    margin-top: 2pt;
    color: #9b9a97;
    font-weight: 500;
}
.card-active   .num { color: #1d7a4c; }
.card-closed   .num { color: #787774; }
.card-trial    .num { color: #9c2b2b; }
.card-med      .num { color: #7a5700; }
.card-disco    .num { color: #2a6495; }

/* ── Section Label ──────────────────────────── */
.section-header {
    font-size: 6.5pt;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #9b9a97;
    padding: 0 0 4pt 0;
    margin: 10pt 0 3pt;
    border-bottom: 0.5pt solid #e9e9e7;
}

/* ── Table ──────────────────────────────────── */
table {
    width: 100%;
    border-collapse: collapse;
    font-size: 7pt;
}
thead th {
    padding: 4pt 5pt;
    text-align: left;
    font-size: 5.5pt;
    font-weight: 500;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: #9b9a97;
    border-bottom: 0.5pt solid #e9e9e7;
    white-space: nowrap;
    background: transparent;
}
tbody td {
    padding: 5pt 5pt;
    border-bottom: 0.4pt solid #f1f0ee;
    vertical-align: middle;
    line-height: 1.3;
}
tbody tr:last-child td { border-bottom: none; }
tbody tr:nth-child(even) td { background: #fafafa; }

.row-closed td { opacity: 0.5; }
.row-closed .col-name { font-style: italic; }

/* ── Columns ────────────────────────────────── */
.col-num    { width: 2%; color: #d3d1ca; font-size: 6pt; text-align: center; }
.col-name   { width: 17%; font-weight: 600; color: #37352f; font-size: 7pt; }
.col-status { width: 7%; }
.col-ptf    { width: 9%; font-size: 6.5pt; color: #37352f; }
.col-ocp    { width: 11%; font-size: 6.5pt; color: #787774; }
.col-ocf    { width: 9%; font-size: 6.5pt; color: #787774; }
.col-adj    { width: 5%; font-size: 6.5pt; color: #787774; }
.col-drv    { width: 5%; font-size: 6.5pt; color: #787774; }
.col-inj    { width: 6%; font-size: 6pt;   color: #9b9a97; }
.col-med    { width: 6%; font-size: 6.5pt; color: #7a5700; font-weight: 500; }
.col-trial  { width: 6%; font-size: 6.5pt; color: #9c2b2b; font-weight: 500; }
.col-cme    { width: 5.5%; font-size: 6.5pt; color: #787774; }
.col-dl     { width: 5.5%; font-size: 6.5pt; color: #2a6495; font-weight: 500; }

/* ── Badge ──────────────────────────────────── */
.badge {
    display: inline-block;
    padding: 1.5pt 5pt;
    border-radius: 3pt;
    font-size: 5.5pt;
    font-weight: 500;
    letter-spacing: 0.02em;
    white-space: nowrap;
}

.empty { color: #d3d1ca; }

/* ── Footer ─────────────────────────────────── */
.footer {
    margin-top: 8pt;
    font-size: 6pt;
    color: #9b9a97;
    border-top: 0.5pt solid #e9e9e7;
    padding-top: 4pt;
    display: flex;
    justify-content: space-between;
}
"""


# ── HTML Builder ──────────────────────────────────────────────────────────────
def build_row(i, c, closed=False):
    status = c['status'] or ''
    theme = get_theme(status)
    badge = (f'<span class="badge" style="background:{theme["bg"]};color:{theme["fg"]};">'
             f'{esc(status)}</span>' if status else '<span class="empty">—</span>')
    name = esc(c['name']) if c['name'] else '<span class="empty">Unnamed</span>'
    row_class = ' class="row-closed"' if closed else ''

    return f"""
        <tr{row_class}>
            <td class="col-num">{i}</td>
            <td class="col-name">{name}</td>
            <td class="col-status">{badge}</td>
            <td class="col-ptf">{fmt_empty(truncate(c['plaintiff'], 32))}</td>
            <td class="col-ocp">{fmt_empty(truncate(c['opp'], 36))}</td>
            <td class="col-ocf">{fmt_empty(truncate(c['oc_firm'], 28))}</td>
            <td class="col-adj">{fmt_empty(c['adjuster'])}</td>
            <td class="col-drv">{fmt_empty(c['driver'])}</td>
            <td class="col-inj">{fmt_empty(c['injury'])}</td>
            <td class="col-med">{fmt_date(c['mediation'])}</td>
            <td class="col-trial">{fmt_date(c['trial'])}</td>
            <td class="col-cme">{fmt_date(c['cme'])}</td>
            <td class="col-dl">{fmt_date(c['next_dl'])}</td>
        </tr>"""


THEAD = """
    <thead>
        <tr>
            <th class="col-num">#</th>
            <th class="col-name">Case</th>
            <th class="col-status">Status</th>
            <th class="col-ptf">Plaintiff</th>
            <th class="col-ocp">Opposing Counsel</th>
            <th class="col-ocf">OC Firm</th>
            <th class="col-adj">Adjuster</th>
            <th class="col-drv">Carrier Driver</th>
            <th class="col-inj">Injury</th>
            <th class="col-med">Mediation</th>
            <th class="col-trial">Trial</th>
            <th class="col-cme">CME</th>
            <th class="col-dl">Next Deadline</th>
        </tr>
    </thead>"""


def build_card(css_class, num, label):
    return f'<div class="card {css_class}"><div class="num">{num}</div><div class="lbl">{label}</div></div>'


def build_html(cases, generated_at):
    stats = compute_stats(cases)
    active_cases = sorted([c for c in cases if not is_closed(c)], key=sort_key)
    closed_cases = sorted([c for c in cases if is_closed(c)], key=sort_key)

    cards = ''.join([
        build_card('card-active', stats['active_count'],    'Active'),
        build_card('card-closed', stats['closed_count'],    'Closed'),
        build_card('card-trial',  stats['trial_count'],     'Trial / Prep'),
        build_card('card-med',    stats['mediation_count'], 'Mediation'),
        build_card('card-disco',  stats['discovery_count'], 'Discovery'),
        build_card('card-med',    stats['has_mediation'],   'w/ Med Date'),
        build_card('card-trial',  stats['has_trial_date'],  'w/ Trial Date'),
    ])

    active_rows = ''.join(build_row(i, c) for i, c in enumerate(active_cases, 1))
    closed_rows = ''.join(build_row(i, c, closed=True)
                          for i, c in enumerate(closed_cases, len(active_cases) + 1))

    closed_section = ''
    if closed_cases:
        closed_section = f"""
<div class="section-header">Closed &amp; Resolved — {len(closed_cases)} matters</div>
<table>{THEAD}<tbody>{closed_rows}</tbody></table>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Legal Matters — Case Management Dashboard</title>
<style>{CSS}</style>
</head>
<body>
<div class="header">
  <div class="header-left">
    <span class="icon">⚖️</span>
    <h1>Legal Matters</h1>
    <div class="sub">Legal Matters Dashboard &nbsp;·&nbsp; <b>{stats['total']} total matters</b> &nbsp;·&nbsp; {stats['active_count']} active &nbsp;·&nbsp; {stats['closed_count']} closed</div>
  </div>
  <div class="header-right">Generated {generated_at}</div>
</div>

<div class="cards">{cards}</div>

<div class="section-header">Active Matters — {len(active_cases)} cases</div>
<table>{THEAD}<tbody>{active_rows}</tbody></table>

{closed_section}

<div class="footer">
  <span>Stonewall Legal Intelligence Platform</span>
  <span>{generated_at}</span>
</div>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='Generate Legal Matters PDF from Notion')
    parser.add_argument('--output', '-o', default='legal_matters.pdf',
                        help='Output PDF path (default: legal_matters.pdf)')
    parser.add_argument('--html', action='store_true',
                        help='Also save the HTML file alongside the PDF')
    args = parser.parse_args()

    if not TOKEN:
        print('ERROR: Set NOTION_TOKEN environment variable')
        sys.exit(1)

    print('═══ Legal Matters PDF Dashboard ═══')
    print(f'Output: {args.output}')
    print()

    print('Fetching Legal Matters from Notion...')
    sorts = [{'property': 'Status', 'direction': 'ascending'}]
    pages = paginate_db(LEGAL_MATTERS_DB, sorts=sorts)
    print(f'  Fetched {len(pages)} cases')

    cases = [extract_case(p) for p in pages]
    cases = [c for c in cases if c['name'].strip()]
    active = [c for c in cases if not is_closed(c)]
    closed = [c for c in cases if is_closed(c)]
    print(f'  {len(active)} active, {len(closed)} closed/settled')

    generated_at = datetime.now().strftime('%B %d, %Y  %I:%M %p')
    html_content = build_html(cases, generated_at)

    html_path = Path(args.output).with_suffix('.html')

    if args.html:
        html_path.write_text(html_content, encoding='utf-8')
        print(f'  HTML saved: {html_path}')

    print('Converting to PDF...')
    try:
        import weasyprint
        weasyprint.HTML(string=html_content).write_pdf(args.output)
        size_kb = os.path.getsize(args.output) // 1024
        print(f'\n  ✓ PDF saved: {args.output} ({size_kb} KB)')
    except ImportError:
        if not args.html:
            html_path.write_text(html_content, encoding='utf-8')
        print(f'\n  weasyprint not available. HTML saved: {html_path}')
        print(f'  Open in Chrome → Ctrl+P → Save as PDF → Landscape')

    print()
    print('═══ DONE ═══')


if __name__ == '__main__':
    main()
