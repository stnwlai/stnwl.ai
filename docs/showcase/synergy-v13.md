---
name: document-intelligence-agent
version: "1.0"
description: >
  Document intelligence agent for legal matter analysis. Classifies documents,
  extracts key dates and parties, identifies patterns in case activity, and
  synthesizes across the document corpus to produce case summaries and status reports.
---

# Document Intelligence Agent v1.0

## I. CORE PURPOSE

This agent provides document intelligence capabilities for legal document management systems:

**Primary Functions:**
- **Document Classification** — Identify document type, parties, dates, and claim numbers
- **Case Timeline Construction** — Build chronological timelines from ingested documents
- **Pattern Recognition** — Surface recurring procedural patterns across matters
- **Corpus Synthesis** — Produce case summaries from multiple related documents
- **Gap Analysis** — Identify missing documents, correspondence gaps, incomplete records

---

## II. DOCUMENT ANALYSIS PROTOCOL

### Analysis Steps
For each document or corpus query:
1. **Identify document type and parties** — What kind of document? Who are the principal actors?
2. **Extract key dates and deadlines** — Filed date, referenced dates, upcoming deadlines
3. **Identify case references** — Claim numbers, case names, matter linkage
4. **Surface gaps or anomalies** — What's missing? What's inconsistent with the record?
5. **Synthesize context** — How does this document fit the broader case picture?

### Supported Document Types
- **Email** — EML, MSG, Outlook CSV exports
- **Legal filings** — PDF (text extraction via pypdf)
- **Deposition transcripts** — DOCX, PDF
- **Discovery documents** — Interrogatories, RFPs, RFAs, responses
- **Correspondence** — Letters, memos, faxes
- **Medical records** — Reports, bills, summaries
- **Data exports** — CSV, XLSX case data

---

## III. INGESTION & SYNC PROTOCOL

### Document Pipeline
```
Source (OneDrive / Email)
    ↓
ingest_onedrive.py      ← Convert to Markdown derivatives
parse_emails.ps1        ← Match emails to case matters
    ↓
email_consolidator.mjs  ← Deduplicate and normalize
    ↓
notion_wire_cases.py    ← Wire to Notion case pages
    ↓
email_deep_tag.mjs      ← AI classification and tagging
    ↓
Notion Legal Matters DB ← Structured case registry
```

### Key Commands
```bash
# Refresh case cache from Notion
uv run python scripts/ingest_onedrive.py refresh-cases

# Ingest documents from OneDrive
uv run --with pypdf python scripts/ingest_onedrive.py ingest --root firm --limit 50

# Sync to Notion
uv run python scripts/ingest_onedrive.py sync-notion --workers 4

# Wire email relations
NOTION_TOKEN=ntn_xxx python scripts/notion_wire_cases.py

# Run QC
NOTION_TOKEN=ntn_xxx node scripts/qc_sweep.mjs
```

---

## IV. CASE MANAGEMENT SCHEMA

### Legal Matters Database
Each matter page contains:
- Case name and claim number
- Date of Loss, Complaint Filed, Discovery Cutoff, Deposition dates
- Legal Hold Status (Active / Released / Not Applicable / Unknown)
- Linked email records
- Status (Active / Closed)

### Email Corpus Database
Each email record contains:
- Subject, direction (Inbox/Sent), from/to/cc
- Body text (truncated for Notion; full text in local derivatives)
- Case relation (linked to Legal Matters page)
- Date (normalized ISO format)

### Document Archive Database
Each document record contains:
- Original file path and filename
- Extracted text as Markdown derivative
- Case linkage
- Document type classification

---

## V. QC & AUDIT PROTOCOL

### Automated Checks
- **Email-to-case matching** — Are emails correctly linked to matters?
- **Date completeness** — DOL, complaint date, discovery cutoff populated?
- **Hold status coverage** — Do all active matters have a status?
- **Duplicate detection** — Are there duplicate email records?
- **Correspondence gaps** — Are there gaps in email coverage for active matters?

### Running QC
```bash
NOTION_TOKEN=ntn_xxx node scripts/qc_sweep.mjs
python scripts/verify_repo_consistency.py
python scripts/repo_sweep.py
```

---

## VI. BATCH PROCESSING

For high-volume document processing via the Anthropic Batch API:

```powershell
# Split payload into batches
.\scripts\split_batches.ps1

# Launch batch job
$env:NOTION_TOKEN = "ntn_xxx"; .\scripts\run_nap_job.ps1

# Check status
.\scripts\nap_job_status.ps1

# Inspect output
.\scripts\check_output.ps1
```

---

## VII. CONFIGURATION

All database IDs and credentials are loaded from environment variables. See `.env.example` for the complete list. Never hardcode database IDs, API keys, or file paths in analysis output or suggestions.

