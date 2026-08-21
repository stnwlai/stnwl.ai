# Docs Drift Watcher

**A scheduled, autonomous editor that keeps your documentation honest about the code it describes.**

> Code ships at the speed of merges. Documentation does not. The Docs Drift Watcher closes the gap on a clock — every day, on its own, with receipts.

---

## The thesis

Every meaningful codebase carries a second product nobody owns: its documentation. The instant a function is renamed, a route retired, or a response field reshaped, the page that taught the world how to use it becomes a quiet liar. The build stays green. The tests stay green. A customer hits the stale example and the trust spend lands on support.

There is no manual workflow that fixes this. Asking authors to "remember the docs" does not scale. Gating every code PR on a doc edit trains reviewers to write throwaway one-liners to get past the bot. The only durable answer is a surveillance layer that knows what changed in the code, knows where each piece is mentioned in the docs, and stages the reconciliation as a single review surface a human editor can dispatch in minutes.

That layer is the Docs Drift Watcher.

---

## What it delivers

| Promise | Mechanism |
| --- | ---: |
| **No silent drift.** | Every PR merged since the last run is reconciled against the docs corpus within 24 hours. |
| **No editor archaeology.** | Drift surfaces as one standing PR with per-page banners, not a backlog of issues. |
| **No false-positive noise.** | Symbol extraction is diff-aware and word-boundary matched, with an in-repo ignore list. |
| **No hidden state.** | The watermark, run history, and per-run report all live in the repository, version-controlled and inspectable. |
| **No bot merges.** | Editors merge. The watcher stages. The two roles never blur. |

---

## A day in the life

```text
  03:00 UTC   Engineer merges PR #4418: rename Matter.dol → Matter.dateOfLoss
  09:42 UTC   Engineer merges PR #4421: drop --pattern flag, add --tag
  13:17 UTC   Docs Drift Watcher fires on schedule
              ├─ Reads .docs-drift/state.json    → last watermark
              ├─ Lists merged PRs since watermark → #4418, #4421
              ├─ Extracts changed symbols         → Matter.dol, dateOfLoss,
              │                                     --pattern, --tag
              ├─ Scans docs/                      → flags 3 pages
              ├─ Writes docs/_drift/REPORT.md     → human-readable
              ├─ Injects sentinel banners         → in each flagged page
              └─ Refreshes docs-drift/auto branch → PR updated in place
  13:18 UTC   Editor receives the standing PR refresh
  13:35 UTC   Editor edits 3 pages, deletes 3 banners, merges
  13:35 UTC   Watermark advances. Loop closes.
```

The whole cycle is seventeen minutes of editor time on a single tab. Without the watcher it is three weeks of customer confusion, then a Friday afternoon of guesswork.

---

## The five stages

```text
            ┌─────────────────────────────────────────────────────────┐
            │  TRIGGER                                                │
            │  .github/workflows/docs-drift-watcher.yml               │
            │  schedule: cron '17 13 * * *'   (daily, 13:17 UTC)      │
            │  workflow_dispatch:             (with optional since=)  │
            └────────────────────────┬────────────────────────────────┘
                                     │
                                     ▼
            ┌─────────────────────────────────────────────────────────┐
            │  STAGE 1 — CHECKPOINT                                   │
            │  Read .docs-drift/state.json                            │
            │  └─ watermark + last PR + last run id                   │
            └────────────────────────┬────────────────────────────────┘
                                     │
                                     ▼
            ┌─────────────────────────────────────────────────────────┐
            │  STAGE 2 — PR HARVEST                                   │
            │  GitHub API → merged PRs since watermark                │
            │  └─ Capped by max_prs_per_run; newest first             │
            └────────────────────────┬────────────────────────────────┘
                                     │
                                     ▼
            ┌─────────────────────────────────────────────────────────┐
            │  STAGE 3 — SYMBOL EXTRACTION                            │
            │  Walk each unified diff and pull:                       │
            │  ├─ Python defs / classes / exports via ast.parse       │
            │  ├─ JS / TS exports + top-level declarations            │
            │  └─ HTTP routes from common framework call shapes       │
            └────────────────────────┬────────────────────────────────┘
                                     │
                                     ▼
            ┌─────────────────────────────────────────────────────────┐
            │  STAGE 4 — DOC SCAN                                     │
            │  Word-boundary match every symbol across docs/ tree     │
            │  ├─ Markdown, HTML, MDX                                 │
            │  └─ Ignore list strips noisy common nouns               │
            └────────────────────────┬────────────────────────────────┘
                                     │
                                     ▼
            ┌─────────────────────────────────────────────────────────┐
            │  STAGE 5 — REVIEW PR                                    │
            │  ├─ Write docs/_drift/REPORT-YYYY-MM-DD.md              │
            │  ├─ Inject sentinel banner atop each flagged page       │
            │  ├─ Force-push docs-drift/auto                          │
            │  └─ Open or refresh the standing review PR              │
            └─────────────────────────────────────────────────────────┘
```

Each stage is small, inspectable, and re-runnable. The script is single-file, stdlib-only Python — re-running with `--dry-run` reproduces the full scan locally with no writes.

---

## What the editor sees

One PR per repo. Always the same branch. Title and body follow a fixed template so it can be triaged from an inbox glance.

```text
Title:  docs: drift reconciliation — 2026-05-22 (3 files, 2 renamed, 1 removed)

Body:
  ## Drift run 2026-05-22 13:17 UTC

  Reviewed 12 PRs merged since 2026-05-21 13:17 UTC.

  ### Flagged pages
  - docs/api/matters.md     ← #4418  Matter.dol renamed → Matter.dateOfLoss
  - docs/cli/search.md      ← #4421  --pattern removed; --tag added
  - docs/portal/usage.md    ← #4421  workflow narrative references --pattern

  ### Receipts
  - run report:   docs/_drift/REPORT-2026-05-22.md
  - run summary:  .docs-drift/last-run.json
  - watermark:    advances to 2026-05-22T13:17:00Z on merge

  Editor: review, edit, delete the banner on each page, merge.
```

Each flagged page receives a self-stripping banner immediately after any YAML frontmatter (or at the very top if there is none):

```markdown
```

The sentinel comments are not decoration. On every subsequent run, the watcher strips the prior banner block before writing the new one, so reruns never stack. Once the editor removes the banner and merges, the page is clean and the watermark advances.

---

## Operator surface

### Schedule

| Mode | How | When you use it |
| --- | --- | --- |
| **Scheduled** | `cron '17 13 * * *'` in the workflow | Default — fires once daily at 13:17 UTC. |
| **Manual** | `workflow_dispatch` with optional `since` input | Backfill after a long quiet window, or re-scan after editor cleanup. |
| **Local** | `python scripts/docs_drift_watcher.py --dry-run` | Tune the ignore list against a real backlog before merging config changes. |

### State

A single JSON file at `.docs-drift/state.json` carries the bot's memory. It is committed to the repo and only advances on merge:

```json
{
  "watermark": "2026-05-21T13:17:00Z",
  "last_run_id": "2026-05-21",
  "last_pr": 142,
  "last_pr_status": "merged",
  "consecutive_failures": 0
}
```

The watermark living in the repository — not in a hosted database — is a deliberate choice. A reviewer auditing a drift PR can read this file and reconstruct what the bot saw without leaving GitHub.

### Config

A flat, minimal YAML at `.docs-drift/config.yml`. Every key has a sane default; an empty file is valid:

```yaml
docs_globs:        [**/*.md, **/*.html, **/*.mdx]
code_extensions:   [.py, .mjs, .js, .ts, .tsx, .jsx]
ignore_symbols:    [self, cls, get, set, list, update, delete, create]
min_symbol_length: 5
ignore_doc_paths:  [docs/_drift/, docs/portal/data/]
max_prs_per_run:   50
base_branch:       main
```

Tuning is in-repo. Changes ride through the same PR review that everything else does.

---

## How the symbol extractor thinks

It reads diffs, not whole files. A symbol counts as "touched" if it appears on a `+` or `-` line in the unified diff. That single design choice gives the watcher its most important property: it catches additions, removals, **and** renames in the same pass, because a rename arrives as a removed old name plus an added new name.

| Surface | Strategy |
| --- | ---: |
| Python (`.py`) | `ast.parse` on the synthesized changed body; falls back to a tolerant `def` / `class` regex when a fragment is not parseable on its own. |
| JS / TS (`.mjs`, `.js`, `.ts`, `.tsx`, `.jsx`) | Regex over `export function`, `export class`, `export const`, top-level `function`, and `class`. |
| HTTP routes | Regex over `@app.route(...)`, `app.get(...)`, `router.post(...)`, and their cousins. Routes bypass the length floor. |

Private symbols (leading underscore in Python, lowercase JS class names) are skipped. Symbols shorter than `min_symbol_length` are skipped unless they are routes. The `ignore_symbols` list strips common verbs that match too eagerly.

---

## Failure modes, and the design's response

| Risk | Behavior |
| --- | --- |
| Source repo unreachable | Run aborts; watermark does **not** advance. Next scheduled run resumes from the same point. |
| API rate limit on a big backlog | `max_prs_per_run` caps the scan window. The next day picks up where this one stopped, because state only advances on merge. |
| Drift PR left unmerged for a week | Each run refreshes the same `docs-drift/auto` branch. New symbols pile into the same open PR until the editor clears it. |
| Default Actions token cannot open PRs | The workflow uses `DOCS_DRIFT_TOKEN` when configured; otherwise it keeps the run green after pushing `docs-drift/auto` and writes manual PR instructions to the run summary. |
| False positive on a common word | Tune `ignore_symbols` in the config; the change rides through normal review. |
| Concurrent runs racing | `concurrency: docs-drift-watcher` prevents two scans pushing to the same branch. |
| Editor closes the PR without merging | Watermark does **not** advance. The next run re-flags the same drift. Move it by hand only if you mean it. |

`fail_open` is the unifying principle: when in doubt, the watcher yields. Editors never inherit a half-built drift PR they cannot trust.

---

## Why this design, not the alternatives

**Why not block every code PR on doc edits?** Wrong loop. The engineer writing the code is rarely the right author for the doc change, and gating PRs on doc review trains everyone to write tiny throwaway edits. The watcher moves the work to a dedicated editor surface where docs get the attention they deserve.

**Why daily, not per-merge?** Per-merge spams editors and coalesces poorly. A daily rollup matches editor cadence, batches related changes — renames usually arrive in clusters — and gives the codebase a quiet window to settle before the scan.

**Why one rolling PR instead of one PR per drift event?** A standing PR is a single tab and a single diff. New events accumulate into the same surface until it is cleared. Reverts happen at the granularity of the drift, not the granularity of the run.

**Why symbol matching, not vector similarity?** Overkill for the failure mode that matters. Drift is overwhelmingly about named identifiers, and word-boundary symbol matching catches what actually breaks readers. A model would add latency, cost, and a new failure surface in exchange for catches we do not need.

**Why state in the repo, not in a database?** One JSON file is auditable with `git log`, conflict-resolvable with normal git tooling, and survives a full rebuild of the runner. If the watcher disappeared tomorrow, the next maintainer could reconstruct it in an afternoon.

**Why editors merge, not the bot?** Tone, completeness, and judgment are editorial work. The watcher does the staging.

---

## Metrics that prove it is working

The watcher appends one line to `.docs-drift/metrics.jsonl` on every run. The dashboard reads from there.

| Metric | What it measures | Why it matters |
| --- | --- | ---: |
| `time_to_reconciliation` | Hours between merge and drift detection | Should stay under 24h. If it climbs, the cron is missing runs. |
| `editor_accept_rate` | Fraction of flagged pages merged without further edit | High rate = sharp extractor. Low rate = drafts need tuning. |
| `false_positive_rate` | Fraction of drift PRs closed without merge | The trust score. Target under 5%. |
| `coverage` | Fraction of merged source PRs that produced any verdict | Detects index decay — paths that stopped being scanned. |
| `streak_clean_runs` | Consecutive runs without a tracking issue | Operational health for the dashboard. |

---

## What it does **not** do

Naming the negative space is part of keeping a tool trustworthy.

- It does not edit documentation outside the configured docs paths.
- It does not rewrite tone, voice, or structure — only stages content edits keyed to the contract change.
- It does not chase third-party API drift. It only watches repositories listed in the config.
- It does not merge. Editors merge.
- It does not promise zero false positives. It promises every PR it opens carries the receipts to falsify it in under a minute.

---

## File map

| Path | Role |
| --- | --- |
| `.github/workflows/docs-drift-watcher.yml` | Schedule trigger, runner, PR plumbing. |
| `scripts/docs_drift_watcher.py` | Single-file scanner. Stdlib only. |
| `.docs-drift/config.yml` | Globs, ignore lists, thresholds. |
| `.docs-drift/state.json` | Last-run watermark (committed). |
| `.docs-drift/last-run.json` | Per-run summary (artifact + commit). |
| `docs/_drift/REPORT-YYYY-MM-DD.md` | Human-readable run report. |
| `tests/test_docs_drift_watcher.py` | Symbol extraction + doc matching coverage. |

---

## Status

| Item | State |
| --- | ---: |
| Schedule | Daily at **13:17 UTC** + `workflow_dispatch` |
| Runtime | Python 3.12 on the GitHub Actions runner; **stdlib only**, no third-party packages |
| Footprint | One workflow, one script, one config, one state file — deletable in a single commit |
| Companion docs | [Technical reference](../overview/docs-drift-watcher.md) · [Design rationale](../overview/docs-drift-sentinel.md) |

When the watcher is doing its job, this page is the only place a new editor needs to read to understand what the bot is, what it will and will not touch, and how to override it.
