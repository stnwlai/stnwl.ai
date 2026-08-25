# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Stonewall is a legal document intelligence platform for law firms handling high-volume civil litigation. It automates email ingestion, document processing, AI-powered tagging, Notion-based case management, and QC reporting.

The platform consists of:
- **`src/stonewall/`** — standard-library evidence compiler, retrieval, citation, bundle, and publication-boundary package
- **`scripts/`** — Python, Node.js, and PowerShell automation scripts
- **`tests/`** — Test suites for the automation scripts
- **`.github/workflows/`** — CI/CD pipeline definitions
- **`.claude/`** — Claude agent configuration (hooks, settings, skills)
- **`agents/`** — OpenAI agent configuration

## Architecture

### Data Flow
```
OneDrive / Email Exports → Ingestion → Processing → Notion Sync → AI Tagging → QC
```

### Key Scripts
- **`scripts/ingest_onedrive.py`** — Primary ingestion pipeline. Walks OneDrive, converts documents to Markdown, syncs to Notion Archive database.
- **`scripts/parse_emails.ps1`** — Parses Outlook CSV exports, matches emails to case matters by keyword.
- **`scripts/email_consolidator.mjs`** — Deduplicates and normalizes email records.
- **`scripts/notion_wire_cases.py`** — Wires email-to-case relations in Notion.
- **`scripts/notion_case_dates.py`** — Syncs case dates to Notion Legal Matters.
- **`scripts/qc_sweep.mjs`** — QC cross-check of Notion data against local index.
- **`scripts/tactical_brief.py`** — CLI daily operating brief from the live corpus.
- **`scripts/legal_matters_pdf.py`** — Generates PDF/HTML case management report.

### Notion Integration
All Notion database IDs are loaded from environment variables. See `.env.example` for the complete list. The primary databases are:
- **Legal Matters** — case registry (env: `NOTION_LEGAL_MATTERS_DB`)
- **All Email** — email corpus with case relations (env: `NOTION_ALL_EMAIL_DB`)
- **Document Archive** — ingested document derivatives (env: `NOTION_ARCHIVE_DB`)

### OneDrive Roots
OneDrive paths are loaded from environment variables:
- `ONEDRIVE_PERSONAL_ROOT` — personal OneDrive root
- `ONEDRIVE_FIRM_ROOT` — firm OneDrive root

## Running Tests

```bash
# Node test suite
node --test tests/tracker_helpers.test.mjs
node --test tests/email_consolidator.test.mjs

# Python test suite
python3 -m unittest discover -s tests -p "test_*.py"

# Evidence reference
PYTHONPATH=src python3 -m stonewall --corpus hoss-stonewall/sample_corpus build --output build/reference
PYTHONPATH=src python3 -m stonewall --corpus hoss-stonewall/sample_corpus query "deposition scheduling" --verify-citations
PYTHONPATH=src python3 -m stonewall --corpus hoss-stonewall/sample_corpus verify --output build/reference
PYTHONPATH=src python3 scripts/check_public_boundary.py
```

## Common Commands

**Refresh case data from Legal Matters:**
```bash
uv run python scripts/ingest_onedrive.py refresh-cases
```

**Ingest documents from OneDrive:**
```bash
uv run --with pypdf --with cryptography python scripts/ingest_onedrive.py ingest --root firm --glob "*.pdf" --limit 50
```

**Sync to Notion:**
```bash
uv run python scripts/ingest_onedrive.py sync-notion --limit 50 --workers 4
```

**Run QC sweep:**
```bash
NOTION_TOKEN=ntn_xxx node scripts/qc_sweep.mjs
```

**Daily brief:**
```bash
python scripts/tactical_brief.py today
python scripts/tactical_brief.py case "smith"
```

**Repo hygiene:**
```bash
python scripts/repo_sweep.py
python scripts/verify_repo_consistency.py
```

| Script | Purpose |
|--------|---------|
| `scripts/ingest_onedrive.py` | Core ingestion engine |
| `scripts/tactical_brief.py` | Daily operating brief CLI |
| `scripts/verify_repo_consistency.py` | Cross-system consistency validation |
| `scripts/repo_sweep.py` | Repo hygiene check |
| `scripts/notion_wire_cases.py` | Case metadata → Notion sync |

- **Never hardcode secrets.** All API keys, tokens, and database IDs must come from environment variables. See `.env.example`.
- **Never hardcode file paths.** Use `ONEDRIVE_PERSONAL_ROOT` and `ONEDRIVE_FIRM_ROOT` environment variables.
- **`refresh-cases` and `sync-notion` require `NOTION_TOKEN`** in the environment. Plain `ingest` does not.
- **Rate limiting** — Notion API has rate limits. The scripts include retry logic with exponential backoff. Do not remove or bypass it.
- **Idempotency** — All sync operations are designed to be idempotent. Running the same operation twice produces the same result.

## Claude Agent Skills

The `.claude/skills/` directory contains custom Claude skills for this platform. See each skill's `SKILL.md` for capabilities and trigger conditions.

## Testing Guidance

- Tests live in `tests/` and use Python `unittest` or Node `--test`.
- `tests/conftest.py` prepends the repo root to `sys.path` so `scripts.*` imports work.
- Run targeted tests for the surface you're changing before opening a PR.
- The CI/CD pipeline runs tests on every push.
