# Docs Drift Watcher

**A daily, autonomous editor that catches stale documentation the moment
your API moves out from under it.**

> Code ships fast. Documentation does not. The Docs Drift Watcher closes
> that gap before it becomes a support ticket, a misled customer, or a
> bad demo.

---

## The problem

Documentation rot is a slow leak. Engineers rename a function, retire a
route, change a parameter shape — and the page that taught the world how
to use it sits there, smiling, lying. Nobody notices until a reader does.

The leak compounds in any repo that ships more than once a week. You
cannot fix it by asking authors to "remember the docs," and you should
not fix it by gating every PR on a manual doc review. You fix it with a
scheduled, deterministic surveillance layer that knows what changed and
where it is mentioned.

That layer is the Docs Drift Watcher.

---

## What it does

Every day at **13:17 UTC**, the watcher runs five steps in order:

1. **Reads the checkpoint.** Opens `.docs-drift/state.json` and learns
   the timestamp and PR number of the last successful run.
2. **Lists merged PRs.** Asks GitHub for everything merged into the base
   branch since that checkpoint, newest first, capped at the configured
   budget.
3. **Extracts API symbols.** Walks each changed code file's unified diff
   and pulls out function names, class names, exported identifiers, and
   route patterns — the things readers actually cite in documentation.
4. **Scans every doc page.** Word-boundary matches each symbol against
   every Markdown, HTML, and MDX file under `docs/`. Generic noise is
   filtered through a configurable ignore list.
5. **Opens a review PR.** Writes a dated drift report into
   `docs/_drift/`, drops an inline editor banner at the top of every
   flagged page, and either opens a new PR or refreshes the standing one
   at `docs-drift/auto`.

The editor sees a single, opinionated PR with every flagged page in one
diff and a clean checklist of what to verify.

---

## Architecture

```text
schedule (13:17 UTC)
        |
        v
   GitHub Actions runner ──── reads .docs-drift/state.json
        |                              |
        |                              v
        |                    GitHub API: merged PRs
        |                              |
        |                              v
        |                    AST + regex symbol extractor
        |                              |
        |                              v
        |                    glob walk over docs/
        |                              |
        |                              v
        |                    drift report + inline banners
        |                              |
        v                              v
   force-push docs-drift/auto ──> open / refresh review PR
        |
        v
   editor reviews → merges → state.json advances on main
```

The state checkpoint is intentionally stored in-repo. It only advances
when the watcher's PR is merged, which means an unattended drift PR
keeps presenting new merges in the same review surface — no silent
gaps, no exponential backoff games.

---

## File map

| Path | Role |
| --- | --- |
| `.github/workflows/docs-drift-watcher.yml` | Schedule trigger, runner, PR plumbing. |
| `scripts/docs_drift_watcher.py` | Single-file scanner. Stdlib only. |
| `.docs-drift/config.yml` | Globs, ignore lists, thresholds. |
| `.docs-drift/state.json` | Last-run checkpoint (committed). |
| `.docs-drift/last-run.json` | Per-run summary (artifact + commit). |
| `docs/_drift/REPORT-YYYY-MM-DD.md` | Dated, human-readable drift report. |
| `tests/test_docs_drift_watcher.py` | Symbol extraction + doc matching coverage. |

---

## What the editor sees

Every flagged page gets a banner injected immediately after any YAML
frontmatter (or at the top when there is none), between sentinel comments.
It looks like this:

```markdown
```

The sentinels are not decoration. The watcher strips any prior banner
before writing a new one, so reruns never stack. Once the editor deletes
the banner block and merges, the page returns to a clean state and the
checkpoint moves forward.

The PR body itself contains the full drift report: scan window, every
flagged page, every symbol, every merged PR reviewed — so a reviewer can
audit the watcher's reasoning without leaving GitHub.

---

## How the symbol extractor thinks

It reads diffs, not whole files. A symbol counts as "touched" if it
appears on a `+` or `-` line in the PR's unified diff. That is the
single most important design choice — it catches additions, removals,
**and** renames in the same pass, because a rename shows up as a removed
old name plus an added new name.

| Language | Strategy |
| --- | --- |
| Python (`.py`) | `ast.parse` on the synthesized added+removed body; falls back to a tolerant `def` / `class` regex when the diff fragment is not parseable on its own. |
| JavaScript / TypeScript (`.mjs`, `.js`, `.ts`, `.tsx`, `.jsx`) | Regex over `export function`, `export class`, `export const`, top-level `function`, and `class` declarations. |
| HTTP routes (any language) | Regex over `@app.route(...)`, `app.get(...)`, `router.post(...)`, and their siblings. Routes never get length-filtered. |

Private symbols (leading underscore in Python, lower-case `class` names
in JS) are skipped. Symbols shorter than `min_symbol_length` are skipped
unless they are routes. The `ignore_symbols` list strips common nouns
that match too eagerly (`get`, `list`, `update`, …).

---

## Configuration

All knobs live in `.docs-drift/config.yml`. The parser is deliberately
tiny — flat keys only, lists in `[a, b, c]` form, no anchors.

```yaml
docs_globs:        [**/*.md, **/*.html, **/*.mdx]
code_extensions:   [.py, .mjs, .js, .ts, .tsx, .jsx]
ignore_symbols:    [self, cls, get, set, list, ...]
min_symbol_length: 5
ignore_doc_paths:  [docs/_drift/, docs/portal/data/]
max_prs_per_run:   50
base_branch:       main
```

The script ships sane defaults for every key, so an empty config file is
valid. Local overrides only need to specify the keys you actually want
to change.

---

## Running it by hand

The workflow exposes `workflow_dispatch` with an optional `since` input:

```text
Actions → Docs Drift Watcher → Run workflow
   since: 2026-05-01T00:00:00Z   (optional — overrides state file)
```

To run it locally against the live repo:

```bash
export GITHUB_TOKEN="<a fine-grained PAT with PR read access>"
python scripts/docs_drift_watcher.py \
  --repo <owner>/<repo> \
  --docs-root docs \
  --apply-banners \
  --dry-run
```

`--dry-run` performs the full scan and prints the summary to stderr
without writing reports, banners, state, or the summary JSON. Useful
for tuning `ignore_symbols` against a real backlog.

---

## Operating modes

### Same-repo docs (default)

Documentation lives at `docs/` next to the code. The workflow scans the
same repo it runs in and opens the review PR there. Configure
`DOCS_DRIFT_TOKEN` when repository policy blocks the default Actions token
from opening PRs; otherwise the watcher pushes `docs-drift/auto` and leaves
manual follow-up instructions in the run summary.

### Cross-repo docs

When documentation lives in a separate repository, run the workflow from
the docs repo with a GitHub App token (or fine-grained PAT) that has
`contents:read` on the source repo and `contents:write` +
`pull-requests:write` on the docs repo. Pass `--docs-repo` so the run
summary records which remote owns the pages; today the scanner still
reads `docs/` from the checked-out workspace (same-repo layout). A
future workflow variant can check out two remotes — the flag is reserved
for that path.

---

## Failure modes, and how the design absorbs them

| Risk | What protects you |
| --- | --- |
| API rate-limit during a big backlog | `max_prs_per_run` cap; the next day picks up where this one stopped because state only advances on merge. |
| False positives on common words | Length floor + `ignore_symbols` + word-boundary regex; tunable in-repo. |
| Stacked banners on repeated runs | Sentinel comments scope the banner block; each rerun strips the prior one before writing a new one. |
| Concurrent runs racing | `concurrency: docs-drift-watcher` group prevents two scans pushing to the same branch. |
| Drift PR sitting unmerged | Workflow refreshes the same `docs-drift/auto` branch each day — the open PR keeps accumulating new symbols until it is merged. |
| Default Actions token cannot open PRs | Workflow prefers `DOCS_DRIFT_TOKEN`; without it, the branch still pushes and the job exits green with manual PR instructions. |

---

## Why this design, not the alternatives

- **Why not block every code PR on doc edits?** Wrong loop. The
  engineer writing the code is rarely the right author for the doc
  change, and blocking PRs trains everyone to write tiny throwaway doc
  edits to get green. This watcher moves the work to a dedicated
  editor surface where docs get the attention they deserve.

- **Why not a vector-similarity model over the doc corpus?** Overkill
  for the failure mode that matters. Drift is overwhelmingly about
  named identifiers, and a word-boundary symbol match catches the
  things that actually break readers. The model would add latency,
  cost, and a new failure surface in exchange for catches we do not
  need.

- **Why one rolling PR instead of one PR per drift event?** Reviewer
  ergonomics. A standing PR is a single tab to keep open and a single
  diff to review. New events accumulate into the same surface until
  it is cleared.

---

## Status

- Schedule: daily at **13:17 UTC** plus manual dispatch.
- Dependencies: Python **3.12** on the GitHub Actions runner (the script
  itself is stdlib-only and runs on **3.10+** locally), plus
  `GITHUB_TOKEN`. No third-party Python packages.
- Footprint: one workflow, one script, one config file, one state
  file. Deletable in a single commit if it ever stops earning its
  keep.
