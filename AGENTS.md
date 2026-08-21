# Repository Guidelines

## Project Structure & Module Organization
`Stonewall` is a legal document intelligence platform with automation scripts in `scripts/`, test coverage in `tests/`, and CI/CD in `.github/workflows/`. AI agent configurations live in `.claude/` and `agents/`. The platform integrates with Notion for case management and OneDrive for document storage.

## Build, Test, and Development Commands
- `node --test tests/tracker_helpers.test.mjs` runs the Node helper tests.
- `node --test tests/email_consolidator.test.mjs` runs the email consolidator tests.
- `python -m unittest discover -s tests -p "test_*.py"` runs the full Python test suite.
- `python scripts/repo_sweep.py` performs repo hygiene checks.
- `python scripts/verify_repo_consistency.py` validates catalog and repo alignment.
- `uv run python scripts/ingest_onedrive.py refresh-cases` refreshes the local case cache from Notion.
- `.\scripts\ingest_onedrive.ps1 ingest --root firm --glob "*.pdf" --limit 20` is the PowerShell shortcut for narrow intake runs.

## Coding Style & Naming Conventions
Use 4-space indentation in Python and keep ESM-style JavaScript consistent with existing files in `scripts/`. Prefer descriptive, lowercase-with-underscores Python filenames such as `verify_repo_consistency.py`. All environment-specific values (database IDs, API keys, file paths) must come from environment variables — never hardcode them.

## Testing Guidelines
Add or update tests when changing `scripts/`. Place Python tests in `tests/` using `test_*.py`. Keep Node tests as `.test.mjs` files mirroring the script they cover. Before opening a PR, run the targeted suite for the surface you changed.

## Commit & Pull Request Guidelines
Use short, imperative commit subjects. Keep each commit scoped to one logical change. PRs should state what changed, which surfaces were touched (`scripts/`, `tests/`, `.github/`), and any required follow-up in Notion or OneDrive.

## Environment & Configuration
All sensitive values are loaded from environment variables. Copy `.env.example` to `.env` and populate before running any scripts. Required variables are documented in `.env.example`. Never commit `.env` or any file containing API keys, tokens, or database IDs.

## Security & Configuration Tips
Do not commit real Notion database IDs, personal file paths, or API keys. Use placeholder values in examples (e.g., `YOUR_NOTION_DATABASE_ID`). `refresh-cases` and `sync-notion` require `NOTION_TOKEN`. Read `CLAUDE.md` before major repo work.

## Showcase Voice & PR Standards

The public showcase is **product marketing**. Every visitor-facing surface — README, `docs/`, the portal, the corpus under `hoss-stonewall/sample_corpus/`, the runbooks — must read like a working platform on display, not like a redacted demo apologizing for what it can't show.

### Banned phrasings on publication surfaces

Do not use any of the following on `README.md`, anything under `docs/`, `hoss-stonewall/README.md`, the corpus, or anything under `archive/`:

- `sanitized` / `sanitization`
- `fictional` / `fictitious`
- `obviously fake`
- `no real {matter, parties, persons, client, case, claim, data, names}`
- `real matter data`
- `private matter` / `private version`
- `internal lore`
- `preserving confidentiality`
- `public-safe`
- `showcase only` / `for showcase purposes` / `for showcase use`

These phrases imply that the visible content is a watered-down stand-in for a hidden privileged corpus. That framing is bad marketing and reads as ethically dubious. The corpus on disk **is** the corpus; the artifacts demonstrate the platform; the platform is the product.

### Allowed (technical, not marketing)

- The `sanitize()` / `_sanitize_field()` ingest helpers (whitespace and field normalization) — real engineering, scoped out of the lint.
- HTML `placeholder="..."` attributes on form inputs.
- Generic example values inside code comments (e.g., `# e.g., "Smith v. Acme Corp"`) — these are normal example syntax, not visitor-facing copy.

### How to write the corpus instead

- Present each artifact as a working artifact. No preamble disclaimers.
- Use neutral generic case captions and let them stand on their own.
- Skip any "this is just an example" language at the top of fixtures.
- Front matter carries `id` and `type`; it does not carry status flags about authenticity.

### Procedure (every PR)

1. Run the lint: `python scripts/check_showcase_voice.py`
2. CI runs the same check on every push (`.github/workflows/verify.yml` → "Showcase voice guard"). A failed lint blocks the PR.
3. If you add a new publication surface (a new file under `docs/`, the corpus, or a new top-level showcase doc), it is automatically scanned by the glob list in `scripts/check_showcase_voice.py`. No manual registration needed.
4. If you genuinely need to discuss the rule itself, do it in `AGENTS.md` or `.github/copilot-instructions.md` — those files are excluded from the scan.

## Repository Presentation

Keep the GitHub repo as clean as the public showcase. Remote branches should be `main` plus any branch with an open PR — nothing else.

- Branch names must describe the work (`cursor/fix-public-content-policy-4a88`), not jokes or session nicknames.
- Delete head branches when PRs merge or close without merge.
- Agents must not leave orphan branches on `origin` without an open PR.

Full rules: [`docs/repository-presentation-policy.md`](docs/repository-presentation-policy.md).

## Cursor Cloud specific instructions

### Runtime environment
- Python 3.12 (`python3`) and Node.js 22 (`node`) are pre-installed.
- `uv` is available at `$HOME/.local/bin/uv`. Source `$HOME/.local/bin/env` if `uv` is not on PATH.
- There is no `package.json` or `requirements.txt`. Python dependencies are injected at runtime via `uv run --with <pkg>`. Node scripts are zero-dependency ESM.

### Running the full CI locally
The CI job in `.github/workflows/verify.yml` defines the canonical check sequence:
```bash
node --test tests/tracker_helpers.test.mjs tests/email_consolidator.test.mjs
python3 -m unittest discover -s tests -p "test_*.py"
python3 scripts/check_showcase_voice.py
python3 scripts/verify_repo_consistency.py
python3 scripts/repo_sweep.py
```

### Notion-dependent scripts
Scripts that call the Notion API (`refresh-cases`, `sync-notion`, `qc_sweep.mjs`, `notion_wire_cases.py`) require `NOTION_TOKEN` and the relevant `NOTION_*_DB` env vars. Without these, they exit with a clear error. The Python test suite mocks Notion calls and runs without a token.

### Key gotchas
- Use `python3` not `python` (the `python` symlink is not present by default).
- `tactical_brief.py` requires `catalog/manifest.md` which is generated by the ingestion pipeline. It will fail if that file doesn't exist.
- `qc_sweep.mjs` requires `scripts/case_index.json` (generated by `refresh-cases`).
- The `ingest` subcommand of `ingest_onedrive.py` requires a case index; provide `--case-index` or run `refresh-cases` first.
- `catalog/intake/` is the output directory for generated reports — it's safe to regenerate at any time.
