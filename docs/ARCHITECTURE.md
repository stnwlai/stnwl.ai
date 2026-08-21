# Architecture — Stonewall Legal Document Intelligence Platform

## System Overview

Stonewall is a multi-layer automation platform that transforms raw legal documents and email correspondence into a structured, searchable intelligence layer wired to Notion for case management.

```
┌─────────────────────────────────────────────────────────────────────┐
│                         SOURCE LAYER                                │
│  OneDrive (PDFs, DOCX, XLSX)    Outlook (CSV Email Exports)         │
└───────────────────────┬─────────────────────────┬───────────────────┘
                        │                         │
                        ▼                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       INGESTION LAYER                               │
│  ingest_onedrive.py            parse_emails.ps1                     │
│  ├─ Walk OneDrive folder tree  ├─ Import Outlook CSV exports        │
│  ├─ Extract text (PDF/DOCX)    ├─ Match emails to case matters      │
│  └─ Write Markdown derivatives └─ Deduplicate by subject+from+to    │
└───────────────────────┬─────────────────────────┬───────────────────┘
                        │                         │
                        ▼                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      PROCESSING LAYER                               │
│  email_consolidator.mjs        docx_to_md.py                        │
│  ├─ Deduplicate email records  transcribe_repo_pdfs.py              │
│  ├─ Normalize field formats    email_to_md.py                       │
│  └─ Build consolidated corpus  email_defuzz.mjs                     │
└───────────────────────┬─────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     NOTION SYNC LAYER                               │
│  notion_wire_cases.py          notion_case_dates.py                 │
│  ├─ Wire email→case relations  ├─ Sync DOL, complaint, depo dates   │
│  notion_wire_batch.py          notion_backfill_legal_matters.py     │
│  ├─ Batch email uploads        ├─ Fill missing matter properties    │
│  notion_consolidate_emails.py  notion_fast_consolidate.py           │
│  └─ Merge datasources          └─ High-throughput consolidation     │
└───────────────────────┬─────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       AI TAGGING LAYER                              │
│  email_deep_tag.mjs            legal_matters_fill.mjs               │
│  ├─ Semantic email classif.    ├─ AI-fill missing properties        │
│  email_audit.mjs               legal_hold_backfill.mjs              │
│  ├─ Audit and repair tagging   └─ Set hold status on matters        │
│  └─ Fix date formatting                                             │
└───────────────────────┬─────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      STORAGE LAYER (NOTION)                         │
│  ┌──────────────────┐  ┌──────────────────┐  ┌───────────────────┐ │
│  │  Legal Matters   │  │   All Email DB   │  │  Document Archive │ │
│  │  ─────────────   │  │  ─────────────   │  │  ───────────────  │ │
│  │  Case registry   │  │  Email corpus    │  │  Markdown derivs  │ │
│  │  Dates & holds   │  │  Case relations  │  │  Case linkage     │ │
│  │  Status & phase  │  │  Full text       │  │  Doc type class.  │ │
│  └──────────────────┘  └──────────────────┘  └───────────────────┘ │
└───────────────────────┬─────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    QC & REPORTING LAYER                             │
│  qc_sweep.mjs                  tactical_brief.py                    │
│  ├─ Cross-check Notion data    ├─ Daily CLI operating brief         │
│  ├─ Flag missing dates/holds   ├─ Upcoming deadlines                │
│  verify_repo_consistency.py    legal_matters_pdf.py                 │
│  ├─ Validate corpus alignment  └─ PDF/HTML case report generator    │
│  repo_sweep.py                                                      │
│  └─ Repository hygiene checks                                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Component Descriptions

### Ingestion Layer

#### `ingest_onedrive.py`
Primary document ingestion pipeline. Walks OneDrive folder trees and converts documents to Markdown derivatives for storage in the repository and sync to Notion.

**Supported formats:** PDF (via pypdf), DOCX (via python-docx), XLSX (via openpyxl), CSV, TXT, HTML, EML, MSG, ZIP (listing only)

**Commands:**
```bash
# Refresh case cache from Legal Matters Notion DB
uv run python scripts/ingest_onedrive.py refresh-cases

# Ingest documents from firm OneDrive
uv run --with pypdf --with cryptography python scripts/ingest_onedrive.py ingest \
  --root firm --glob "*.pdf" --limit 50

# Sync ingested documents to Notion Archive
uv run python scripts/ingest_onedrive.py sync-notion --limit 50 --workers 4
```

#### `parse_emails.ps1`
Parses Outlook CSV exports (inbox and sent) and matches emails to case matters by keyword and claim number patterns. Outputs a `matched_emails.json` file for downstream processing.

**Configuration:** Populate the `$cases` array with your firm's matters, Notion page IDs, and matching keywords. Set input CSV paths via `$files` array.

---

### Processing Layer

#### `email_consolidator.mjs`
Deduplicates email records across multiple import batches. Normalizes field formats and builds a consolidated JSON corpus.

#### `email_defuzz.mjs`
Fuzzy-matches email records against existing Notion pages to prevent duplicate uploads.

#### `docx_to_md.py` / `transcribe_repo_pdfs.py`
Standalone converters for DOCX and PDF documents to Markdown format.

---

### Notion Sync Layer

#### `notion_wire_cases.py`
Wires email records to their corresponding Legal Matters pages in Notion. Creates `relation` properties linking email pages to case pages.

**Required env:** `NOTION_TOKEN`, `NOTION_LEGAL_MATTERS_DB`, `NOTION_ALL_EMAIL_DB`

#### `notion_case_dates.py`
Syncs case dates from a CSV file to the Notion Legal Matters database. Supports Date of Loss, Complaint Filed, Discovery Cutoff, Deposition dates, Reserve, and Incurred.

**Input format:** CSV with columns: `case_name` (or `page_id`), date/money/checkbox fields

#### `notion_backfill_legal_matters.py`
Backfills missing properties on Legal Matters pages by reading existing Notion data and filling gaps.

---

### AI Tagging Layer

#### `email_deep_tag.mjs`
Uses the OpenAI API to semantically classify email content, assign document types, and tag case relevance.

#### `legal_matters_fill.mjs`
Uses AI to fill missing properties on Legal Matters pages (opposing counsel firm, case phase, etc.) by analyzing the email corpus.

#### `legal_hold_backfill.mjs`
Sets Legal Hold Status on matters where the field is blank. Configure the `ACTIVE_HOLD`, `NOT_APPLICABLE`, and `RELEASED` arrays with your firm's case names.

---

### Storage Layer (Notion Databases)

| Database | Purpose | Primary Fields |
|---|---|---|
| **Legal Matters** | Case registry | Case Name, Claim #, DOL, Complaint Date, Discovery Cutoff, Depo Date, Legal Hold Status, Phase, Reserve |
| **All Email** | Email corpus | Subject, Direction, From, To, CC, Date, Body, Case (relation) |
| **Document Archive** | Ingested docs | File Path, Document Type, Case (relation), Extracted Text |

---

### QC & Reporting Layer

#### `qc_sweep.mjs`
Comprehensive QC audit. Cross-checks Notion database data against the local case index and email corpus. Flags:
- Emails not linked to cases
- Cases missing key date fields
- Matters without Legal Hold Status
- Duplicate email records

**Output:** Console report with counts and specific flagged items

#### `tactical_brief.py`
CLI tool for a daily operating brief. Reads the live corpus and produces:
- Upcoming deadlines (within configurable window)
- Recent case activity
- Inbox backlog
- Uncataloged documents

```bash
python scripts/tactical_brief.py today
python scripts/tactical_brief.py case "smith"
```

#### `legal_matters_pdf.py`
Generates a PDF or HTML case management dashboard from the Notion Legal Matters database. Includes matter cards with key dates, hold status, and phase.

```bash
NOTION_TOKEN=ntn_xxx python scripts/legal_matters_pdf.py --html -o dashboard.html
```

---

## Integration Points

### Notion API
- **Authentication:** Bearer token via `NOTION_TOKEN` env var
- **Rate limiting:** Scripts include exponential backoff retry logic
- **Pagination:** All database queries use cursor-based pagination (`page_size: 100`)
- **API version:** `2022-06-28` or `2025-09-03` (per script)

### Microsoft OneDrive
- **Access:** Direct filesystem access (no OAuth required for local OneDrive sync)
- **Paths:** Configured via `ONEDRIVE_PERSONAL_ROOT` and `ONEDRIVE_FIRM_ROOT` env vars
- **Traversal:** `ingest_onedrive.py` recursively walks configured roots with glob filters

### Anthropic Claude API
- **Authentication:** `ANTHROPIC_API_KEY` env var
- **Use cases:** Document classification, case narrative synthesis, batch processing via Batch API

### OpenAI API
- **Authentication:** `OPENAI_API_KEY` env var
- **Use cases:** Email semantic tagging, property auto-fill

### GitHub Actions CI/CD
- **Triggers:** Push to main/PR branches
- **Jobs:** QC sweep, consistency check, static site deployment
- **Secrets:** API keys stored as GitHub Actions secrets

---

## Data Flow Summary

```
1. Source documents arrive in OneDrive or as Outlook CSV exports

2. Ingestion layer converts to structured data:
   - Documents → Markdown derivatives (repo)
   - Emails → matched_emails.json (local)

3. Processing layer normalizes and deduplicates the data

4. Notion sync layer uploads to the appropriate database and wires relations

5. AI tagging layer classifies documents and fills missing properties

6. QC layer validates data integrity on every push

7. Reporting layer surfaces actionable intelligence via CLI and dashboards
```

---

## Deployment Notes

### Prerequisites
- Python 3.12 with the `uv` package manager
- Node.js 22
- PowerShell 7+
- A Notion workspace with an integration token and the required databases set up
- Anthropic API key (for Claude-powered features)
- OpenAI API key (for GPT-powered features)

### Setup

There are no dependency manifests to install. The Node scripts are
zero-dependency ESM, and Python scripts that need extraction libraries take
them at runtime through `uv run --with <pkg>`:

```bash
# Configure environment
cp .env.example .env
# Edit .env with your credentials and database IDs

# Example: runtime dependency injection for PDF ingestion
uv run --with pypdf --with cryptography python scripts/ingest_onedrive.py ingest \
  --root firm --glob "*.pdf" --limit 20
```

### Database Setup
Create the following Notion databases in your workspace and populate the corresponding env vars in `.env`:
1. **Legal Matters** — one page per matter (see schema above)
2. **All Email** — email corpus database
3. **Document Archive** — ingested document derivatives

See the scripts themselves for the complete property schemas expected in each database.
