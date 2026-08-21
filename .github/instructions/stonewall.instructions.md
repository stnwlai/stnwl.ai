# Stonewall — Legal Document Intelligence Platform
# GitHub Copilot Custom Instructions

## Project Overview

Stonewall is a legal document intelligence platform for law firms handling high-volume civil litigation. The platform automates email ingestion, AI-powered document tagging, Notion-based case management, and QC reporting.

Core components:
- **`scripts/`** — Automation pipeline (Python, Node.js, PowerShell)
- **`tests/`** — Test suites
- **`.github/workflows/`** — CI/CD pipelines
- **`.claude/`** — Claude agent configuration
- **`agents/`** — OpenAI agent configuration

## Repository Structure

```text
scripts/                - Automation pipeline scripts
  ingest_onedrive.py    - Primary document ingestion (OneDrive → Markdown → Notion)
  parse_emails.ps1      - Email CSV parser and case matcher
  email_consolidator.mjs - Email deduplication and normalization
  notion_wire_cases.py  - Email-to-case relation wiring
  notion_case_dates.py  - Case date sync to Notion
  qc_sweep.mjs          - QC cross-check sweep
  tactical_brief.py     - CLI daily operating brief
  legal_matters_pdf.py  - Case management report generator
tests/                  - Test suites (Python unittest, Node --test)
.github/workflows/      - CI/CD pipeline definitions
.claude/                - Claude Code configuration and skills
agents/                 - OpenAI agent configuration
stonewall_synergy_v13.md - Document intelligence system prompt
SKILL.md                - Document intelligence skill definition
```

## Development Guidelines

### Testing
```bash
# Python suite
python -m unittest discover -s tests -p "test_*.py"

# Node suite
node --test tests/tracker_helpers.test.mjs
node --test tests/email_consolidator.test.mjs
```

### Key Commands
```bash
# Refresh case data
uv run python scripts/ingest_onedrive.py refresh-cases

# Ingest documents
uv run --with pypdf python scripts/ingest_onedrive.py ingest --root firm --limit 50

# Sync to Notion
uv run python scripts/ingest_onedrive.py sync-notion --workers 4

# QC sweep
NOTION_TOKEN=ntn_xxx node scripts/qc_sweep.mjs

# Daily brief
python scripts/tactical_brief.py today
```

## Configuration Rules

- All API keys and database IDs come from environment variables — see `.env.example`
- Never hardcode Notion database IDs, personal file paths, or credentials
- `NOTION_TOKEN` is required for any Notion sync operation
- `ONEDRIVE_PERSONAL_ROOT` and `ONEDRIVE_FIRM_ROOT` set OneDrive paths

## What This Project Does

- Ingests legal documents from OneDrive and converts to Markdown derivatives
- Parses email exports and matches to case matters by keyword
- Syncs all case activity to Notion databases (Legal Matters, All Email, Document Archive)
- Classifies documents using AI (Claude, OpenAI)
- Runs automated QC checks on every push
- Generates tactical briefings and case management reports
