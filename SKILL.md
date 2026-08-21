---
name: document-intelligence
description: Legal document intelligence skill for case analysis, document classification, pattern identification, and corpus synthesis across the Stonewall platform. Use when the user asks about case documents, email patterns, filing analysis, or wants synthesis from the document corpus.
---

# Document Intelligence Skill

---

## I. CORE CAPABILITIES

**Document Classification** — Classify legal documents by type (motion, deposition, discovery, correspondence, filing), identify parties, extract key dates and claim numbers.

**Email Corpus Analysis** — Identify patterns in case-related email traffic, flag missing correspondence, surface gaps in the record.

**Case Timeline Construction** — Build chronological case timelines from ingested documents, cross-referenced against case dates in Notion.

**Pattern Recognition** — Identify recurring procedural patterns across matters (discovery delays, response gaps, filing sequences).

**Corpus Synthesis** — Synthesize across multiple documents in a matter to produce a coherent case narrative or status summary.

---

## II. OPERATIONAL PROTOCOL

### Document Analysis Steps
For each document or corpus query:
1. **Identify document type and parties** — What kind of document? Who are the principal actors?
2. **Extract key dates and deadlines** — When was it filed? What dates does it reference?
3. **Identify claim numbers and case references** — What matter(s) does it belong to?
4. **Surface gaps or anomalies** — What's missing? What's inconsistent?
5. **Synthesize context** — How does this document fit the broader case picture?

### Corpus Search Protocol
Before composing any analysis:
1. Consult the Notion Legal Matters database for canonical matter metadata and key dates
2. If available, use any generated local case index or date cache as a secondary reference for faster lookup (not as source of truth)
3. Cross-reference the email corpus for related correspondence and communication gaps
4. Confirm current case status and most recent activity in Notion before finalizing analysis

---

## III. DOCUMENT PROCESSING PIPELINE

### Ingestion Flow
```
Source Documents (OneDrive)
    ↓
ingest_onedrive.py         ← Convert to Markdown derivatives
    ↓
parse_emails.ps1           ← Match emails to case matters
    ↓
email_consolidator.mjs     ← Deduplicate and normalize
    ↓
notion_wire_cases.py       ← Wire to Notion case pages
    ↓
email_deep_tag.mjs         ← AI classification and tagging
    ↓
Notion Legal Matters DB    ← Structured case registry
```

### Supported Document Types
- **Email** — EML, MSG, Outlook CSV exports
- **Legal filings** — PDF (via pypdf extraction)
- **Transcripts** — DOCX (via python-docx), PDF
- **Correspondence** — PDF, DOCX, TXT
- **Data exports** — CSV, XLSX, JSON

---

## IV. CASE MANAGEMENT INTEGRATION

### Notion Database Structure
The platform maintains three primary Notion databases:

**Legal Matters** — One page per case matter. Contains:
- Case name and claim number
- Date of Loss, Complaint Filed, Discovery Cutoff, Deposition dates
- Legal Hold Status (Active/Released/Not Applicable/Unknown)
- Linked email records
- Status (Active/Closed)

**All Email** — One page per email record. Contains:
- Subject, direction (Inbox/Sent), from/to
- Body text (truncated to 2,000 characters for Notion)
- Case relation (linked to Legal Matters page)
- Date (normalized ISO format)

**Document Archive** — One page per ingested document. Contains:
- Original file path and filename
- Extracted text (Markdown derivative)
- Case linkage
- Document type classification

### Sync Commands
```bash
# Refresh case data
uv run python scripts/ingest_onedrive.py refresh-cases

# Sync new documents to Notion
uv run python scripts/ingest_onedrive.py sync-notion --workers 4

# Wire email relations
NOTION_TOKEN=ntn_xxx python scripts/notion_wire_cases.py

# Update case dates from CSV
NOTION_TOKEN=ntn_xxx python scripts/notion_case_dates.py case_dates.csv
```

---

## V. QC & AUDIT CAPABILITIES

### Automated QC Checks
- **Email-to-case matching accuracy** — Are emails correctly linked to matters?
- **Date field completeness** — Are DOL, complaint date, discovery cutoff populated?
- **Legal hold status coverage** — Do all active matters have a hold status?
- **Duplicate detection** — Are there duplicate email records in the corpus?
- **Missing correspondence** — Are there gaps in email coverage for active matters?

### Running QC
```bash
# Full QC sweep
NOTION_TOKEN=ntn_xxx node scripts/qc_sweep.mjs

# Repo consistency check
python scripts/verify_repo_consistency.py

# Hygiene check
python scripts/repo_sweep.py
```

---

## VI. BATCH PROCESSING

For high-volume document processing using the Anthropic Batch API:

```bash
# Split large payload into batches
.\scripts\split_batches.ps1

# Launch batch job
$env:NOTION_TOKEN = "ntn_xxx"; .\scripts\run_nap_job.ps1

# Check job status
.\scripts\nap_job_status.ps1

# Inspect output
.\scripts\check_output.ps1
```

Batch jobs are stored in `scripts/batches/`. Each batch is a JSON payload of up to 50 records, processed asynchronously via the Batch API.
