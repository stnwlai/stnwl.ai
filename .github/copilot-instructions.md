# GitHub Copilot Custom Instructions
# Stonewall — Legal Document Intelligence Platform

## Project Identity

This is a legal document intelligence platform for law firms handling high-volume civil litigation. The platform automates email ingestion, document processing, AI-powered classification, Notion-based case management, and QC reporting.

**Primary Languages:** Python, JavaScript/TypeScript (ESM), PowerShell
**Key Integrations:** Notion API, Anthropic Claude API, OpenAI API, Microsoft OneDrive
**Version Control:** Git/GitHub

---

## Tech Stack & Environment

- **Runtime:** Python 3.11+, Node.js 20+ (ESM modules), PowerShell 7+
- **Package Management:** `uv` (Python), `npm` (Node.js)
- **AI:** Anthropic Claude API, OpenAI API
- **Case Management:** Notion API
- **Document Storage:** Microsoft OneDrive
- **CI/CD:** GitHub Actions

---

## Coding Style & Conventions

### General Principles

1. **Clarity over cleverness.** Each function has a clear purpose, each variable name tells you what it holds, each module has defined boundaries.

2. **Defensive programming.** Validate all inputs. Handle edge cases. Never trust external data without verification.

3. **Championship error handling.** Catch errors, log with context, handle gracefully. No silent failures. No bare `except: pass`. Every error message should tell you what went wrong and where.

4. **No hardcoded credentials or IDs.** All API keys, tokens, and database IDs come from environment variables. See `.env.example`.

### Python Conventions

```python
def process_documents(
    file_paths: list[Path],
    case_id: str,
    output_dir: Path,
) -> ProcessingResult:
    """
    Process a batch of legal documents through the ingestion pipeline.

    Converts source documents to Markdown derivatives, extracts key
    dates and parties, and returns structured processing results.

    Args:
        file_paths: List of document paths to process
        case_id: Notion page ID for the target case matter
        output_dir: Directory for Markdown output files

    Returns:
        ProcessingResult with per-file outcomes and aggregate stats

    Raises:
        IntakeError: If output directory cannot be created
        NotionError: If case page cannot be found
    """
    results = []
    for path in file_paths:
        result = _convert_single_document(path, output_dir)
        results.append(result)
    return ProcessingResult(results=results, case_id=case_id)
```

- Use type hints on all function signatures
- Use Google-style docstrings with Args/Returns/Raises
- Prefer `pathlib.Path` over `os.path`
- Use `dataclasses` or `pydantic` models for structured data
- Use f-strings for string formatting
- Line length: 88 characters (Black formatter default)
- Imports: stdlib → third-party → local

### JavaScript/TypeScript Conventions

- Use ESM (`import`/`export`) consistently — this codebase uses `.mjs` extension
- Use `const` by default; `let` only when mutation is required
- Use async/await over raw Promises
- Use named exports over default exports

---

## Domain-Specific Knowledge

### Legal Document Processing

When working with document ingestion or classification:

- **Supported types:** PDF, DOCX, XLSX, CSV, EML, MSG, TXT, HTML, XML, ZIP
- **Key extractors:** pypdf for PDFs, python-docx for DOCX, openpyxl for XLSX
- **Date formats:** Legal documents may use M/D/YYYY, MM/DD/YYYY, or text formats — normalize to ISO 8601 (YYYY-MM-DD) for storage
- **Claim numbers:** May appear in carrier-specific formats like `CL#XXXXXX` or letter-prefixed digit runs — extract and index these for case matching

### Notion Integration

When writing scripts that interact with Notion:

- All database IDs come from environment variables (see `.env.example`)
- Use `NOTION_TOKEN` env var for the integration token
- Primary databases: `NOTION_LEGAL_MATTERS_DB`, `NOTION_ALL_EMAIL_DB`, `NOTION_ARCHIVE_DB`
- Always include retry logic with exponential backoff for Notion API calls
- Respect rate limits — use the `retry-after` header when rate-limited
- Paginate all database queries (`page_size: 100`, follow `has_more` / `next_cursor`)

### OneDrive Integration

- Personal OneDrive root: `ONEDRIVE_PERSONAL_ROOT` env var
- Firm OneDrive root: `ONEDRIVE_FIRM_ROOT` env var
- Never hardcode file paths — always use env vars or relative paths from repo root

---

## File & Project Structure

```
stonewall/
├── scripts/              - Automation pipeline scripts
│   ├── ingest_onedrive.py
│   ├── parse_emails.ps1
│   ├── email_consolidator.mjs
│   ├── notion_wire_cases.py
│   ├── notion_case_dates.py
│   ├── qc_sweep.mjs
│   ├── tactical_brief.py
│   └── ...
├── tests/                - Test suites
├── .github/
│   ├── workflows/        - CI/CD pipeline definitions
│   └── instructions/     - Copilot instruction files
├── .claude/              - Claude Code configuration
├── agents/               - OpenAI agent configuration
├── .env.example          - Environment variable template
├── requirements.txt      - Python dependencies
└── package.json          - Node.js dependencies
```

---

## Testing Philosophy

- Use Python `unittest` for Python scripts, Node `--test` for JavaScript
- Name test functions descriptively: `test_parse_email_matches_claim_number()`
- Use `tests/conftest.py` to set up Python path for `scripts.*` imports
- Functions that handle API calls or file I/O must have test coverage
- Mock external calls (Notion API, file system) in unit tests

---

## Security Rules

- **NEVER** commit API keys, tokens, Notion database IDs, or personal file paths
- Use `.env` files for sensitive configuration — `.env` is in `.gitignore`
- Use `.env.example` with placeholder values for documentation
- All API keys (Anthropic, OpenAI, Notion) must be environment variables
- When generating test fixtures, use generic neutral data (no real client information)

---

## Showcase Voice & PR Standards (publication surfaces)

The repo doubles as a public showcase. Visitor-facing surfaces — `README.md`, anything under `docs/`, `hoss-stonewall/README.md`, the corpus under `hoss-stonewall/sample_corpus/`, anything under `archive/` — are **product marketing**. They must read like a working platform on display, not like a redacted demo.

**Banned phrasings on those surfaces** (case-insensitive):

- `sanitized` / `sanitization`
- `fictional` / `fictitious`
- `obviously fake`
- `no real {matter, parties, persons, client, case, claim, data, names}`
- `real matter data`
- `private matter` / `private version` / `internal lore`
- `preserving confidentiality`
- `public-safe`
- `showcase only` / `for showcase purposes` / `for showcase use`

These phrases imply the visible content is a watered-down stand-in for a hidden privileged corpus. That framing is bad marketing and reads as ethically dubious. **The corpus on disk is the corpus.**

**Technical uses are fine and scoped out of the lint:** the `sanitize()` / `_sanitize_field()` ingest helpers, HTML `placeholder=` attributes, and example values inside code comments.

**Procedure:**

1. Run `python scripts/check_showcase_voice.py` before opening a PR.
2. The same lint runs in CI (`.github/workflows/verify.yml` → "Showcase voice guard") on every push and blocks the PR if it fails.
3. New surfaces under `docs/`, the corpus, or `archive/` are automatically picked up by the glob list in `scripts/check_showcase_voice.py`.

---

## Repository Presentation

Keep `origin` trimmed: `main` plus open-PR branches only. Delete merged head branches immediately. Branch names must describe the work — no joke or meme names (`naughty-boy-handling` is the canonical anti-pattern). Full rules: `docs/repository-presentation-policy.md`.

---

## Commit Message Format

```
<type>(<scope>): <description>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`

Examples:
```
feat(ingest): add DOCX extraction via python-docx
fix(notion): handle rate limit retry-after header
test(email): add test for duplicate detection logic
```
