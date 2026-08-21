#!/usr/bin/env python3
"""
Email to Markdown — Stonewall Legal Intelligence Platform
==========================================
Reads consolidated_emails.json and generates:
1. EMAIL_MASTER_INDEX.md — metadata table for quick scanning
2. Per-month .md files in sources/emails/md/ with full body text

Usage:
  python3 scripts/email_to_md.py
"""

import json
import os
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.join(SCRIPT_DIR, '..')
EMAILS_JSON = os.path.join(REPO_DIR, 'sources', 'emails', 'consolidated_emails.json')
EMAILS_DIR = os.path.join(REPO_DIR, 'sources', 'emails')
MD_DIR = os.path.join(EMAILS_DIR, 'md')

os.makedirs(MD_DIR, exist_ok=True)


def load_emails():
    with open(EMAILS_JSON) as f:
        return json.load(f)


def clean_cell(text, max_len=80):
    """Clean text for markdown table cells."""
    if not text:
        return ''
    return text.replace('|', '/').replace('\n', ' ').replace('\r', '').strip()[:max_len]


def write_master_index(emails):
    """Write EMAIL_MASTER_INDEX.md with metadata table."""
    path = os.path.join(EMAILS_DIR, 'EMAIL_MASTER_INDEX.md')

    # Group by month
    by_month = defaultdict(list)
    for e in emails:
        month = (e.get('dateShort') or 'unknown')[:7]
        by_month[month].append(e)

    with open(path, 'w') as f:
        f.write('---\n')
        f.write('type: email_index\n')
        f.write(f'total_emails: {len(emails)}\n')
        f.write(f'date_range: {emails[0].get("dateShort", "?") if emails else "?"} to {emails[-1].get("dateShort", "?") if emails else "?"}\n')
        f.write('generated_by: email_to_md.py\n')
        f.write('---\n\n')
        f.write('# Email Master Index — Stonewall Legal Intelligence Platform\n\n')
        f.write(f'**Total emails:** {len(emails)}  \n')
        sent = sum(1 for e in emails if e.get('direction') == 'Sent')
        inbox = len(emails) - sent
        f.write(f'**Sent:** {sent} | **Inbox:** {inbox}  \n\n')

        for month in sorted(by_month.keys()):
            month_emails = by_month[month]
            f.write(f'## {month} ({len(month_emails)} emails)\n\n')
            f.write(f'| Date | Direction | From | To | Subject |\n')
            f.write(f'|------|-----------|------|----|---------|\n')
            for e in month_emails:
                date = e.get('dateShort', '')
                direction = e.get('direction', '')
                frm = clean_cell(e.get('from', ''), 30)
                to = clean_cell(e.get('to', ''), 30)
                subj = clean_cell(e.get('subject', ''), 60)
                f.write(f'| {date} | {direction} | {frm} | {to} | {subj} |\n')
            f.write('\n')

    print(f'Wrote {path} ({len(emails)} emails)')


def write_monthly_files(emails):
    """Write per-month .md files with full body text."""
    by_month = defaultdict(list)
    for e in emails:
        month = (e.get('dateShort') or 'unknown')[:7]
        by_month[month].append(e)

    for month, month_emails in sorted(by_month.items()):
        safe_month = month.replace('-', '_')
        path = os.path.join(MD_DIR, f'emails_{safe_month}.md')

        with open(path, 'w') as f:
            f.write('---\n')
            f.write(f'type: email_archive\n')
            f.write(f'month: {month}\n')
            f.write(f'total_emails: {len(month_emails)}\n')
            f.write('---\n\n')
            f.write(f'# Email Archive — {month}\n\n')
            f.write(f'**{len(month_emails)} emails**\n\n')
            f.write('---\n\n')

            for i, e in enumerate(month_emails, 1):
                date = e.get('dateShort', 'unknown')
                direction = e.get('direction', '')
                frm = e.get('from', '')
                to = e.get('to', '')
                cc = e.get('cc', '')
                subj = e.get('subject', '(no subject)')
                body = e.get('body', '')

                f.write(f'## [{i}] {subj}\n\n')
                f.write(f'- **Date:** {date}  \n')
                f.write(f'- **Direction:** {direction}  \n')
                f.write(f'- **From:** {frm}  \n')
                f.write(f'- **To:** {to}  \n')
                if cc:
                    f.write(f'- **CC:** {cc}  \n')
                f.write('\n')

                if body and body.strip():
                    f.write('### Body\n\n')
                    f.write('```\n')
                    f.write(body.strip())
                    f.write('\n```\n\n')
                else:
                    f.write('*No body text*\n\n')

                f.write('---\n\n')

        print(f'Wrote {path} ({len(month_emails)} emails)')


def main():
    print('=== EMAIL TO MARKDOWN — Stonewall Legal Intelligence Platform ===\n')
    emails = load_emails()
    print(f'Loaded {len(emails)} emails\n')

    # Sort by date
    emails.sort(key=lambda e: e.get('date') or '')

    write_master_index(emails)
    write_monthly_files(emails)

    print('\n=== COMPLETE ===')


if __name__ == '__main__':
    main()
