# Docs Drift Sentinel

**A scheduled watcher that keeps documentation honest about the code it describes.**

Every day, Sentinel reads what merged into the codebase, asks one question of every doc page that references the changed surface — *is this still true?* — and stages the answer as a pull request a human editor can review in minutes instead of hours.

---

## The pitch

Documentation drifts the moment code ships. A renamed parameter, a removed field, a tightened response contract — none of these break the build, all of them break the docs, and nobody finds out until a customer hits the wrong example.

Sentinel closes that loop on a clock.

| Promise | Mechanism |
| --- | ---: |
| **No silent drift.** | Every merged PR is reconciled against the docs corpus within 24 hours. |
| **No editor archaeology.** | Drift surfaces as a single rollup PR with file-level annotations, not a backlog of issues. |
| **No false positives that train reviewers to ignore the bot.** | API surface extraction is symbol-aware, not regex spray. |
| **No hand-rolled state.** | Watermarks, run history, and idempotency keys live in the repository, version-controlled and inspectable. |

---

## How it works

Sentinel is five small, inspectable stages chained on a daily cron. Each stage writes a sidecar artifact so a human can stop the pipeline anywhere, look at what it produced, and know exactly why the next stage made the call it made.

```text
            ┌─────────────────────────────────────────────────────────┐
            │  TRIGGER LAYER                                          │
            │  .github/workflows/docs-drift-sentinel.yml              │
            │  schedule: cron '0 13 * * *'  (daily, 13:00 UTC)        │
            │  workflow_dispatch: manual override                     │
            └────────────────────────┬────────────────────────────────┘
                                     │
                                     ▼
            ┌─────────────────────────────────────────────────────────┐
            │  STAGE 1 — PR HARVEST                                   │
            │  scripts/sentinel/harvest_prs.py                        │
            │  ├─ Read watermark from .sentinel/state.json            │
            │  ├─ List PRs merged since watermark (default branch)    │
            │  ├─ Fetch diffs, labels, linked issues                  │
            │  └─ Write .sentinel/runs/<run-id>/prs.jsonl             │
            └────────────────────────┬────────────────────────────────┘
                                     │
                                     ▼
            ┌─────────────────────────────────────────────────────────┐
            │  STAGE 2 — API SURFACE EXTRACTION                       │
            │  scripts/sentinel/extract_api_surface.py                │
            │  ├─ Walk diffs, classify by file role                   │
            │  ├─ Resolve exported symbols, route paths, schema keys  │
            │  ├─ Detect signature, contract, and rename changes      │
            │  └─ Write .sentinel/runs/<run-id>/surface.jsonl         │
            └────────────────────────┬────────────────────────────────┘
                                     │
                                     ▼
            ┌─────────────────────────────────────────────────────────┐
            │  STAGE 3 — DOC REFERENCE INDEX                          │
            │  scripts/sentinel/index_doc_refs.py                     │
            │  ├─ Build / refresh symbol → doc-file inverted index    │
            │  ├─ Resolve fenced code, signatures, prose references   │
            │  └─ Write .sentinel/index/refs.json                     │
            └────────────────────────┬────────────────────────────────┘
                                     │
                                     ▼
            ┌─────────────────────────────────────────────────────────┐
            │  STAGE 4 — DRIFT REPORT                                 │
            │  scripts/sentinel/compose_drift.py                      │
            │  ├─ Join surface × refs                                 │
            │  ├─ Score each hit (signature / contract / cosmetic)    │
            │  ├─ Draft suggested edits (Claude, low temp)            │
            │  └─ Write .sentinel/runs/<run-id>/drift.md              │
            └────────────────────────┬────────────────────────────────┘
                                     │
                                     ▼
            ┌─────────────────────────────────────────────────────────┐
            │  STAGE 5 — PR DELIVERY                                  │
            │  scripts/sentinel/open_pr.py                            │
            │  ├─ Branch: sentinel/drift-<run-id>                     │
            │  ├─ One rollup PR against docs repo (default branch)    │
            │  ├─ Labels: docs-drift, sentinel, needs-editor          │
            │  ├─ Auto-assign editor rota from .sentinel/config.yml   │
            │  └─ Advance watermark in .sentinel/state.json           │
            └─────────────────────────────────────────────────────────┘
```

Every stage is a standalone script. Re-running stage N with a fixed `--run-id` is idempotent — Sentinel is debuggable the same way a unix pipeline is debuggable.

---

## What gets flagged

Sentinel does not flag every diff. It flags diffs that *change the contract a doc is making to a reader*. The classifier produces one of four labels per matched doc:

| Label | Trigger | Example | Editor action |
| --- | --- | --- | --- |
| **Breaking** | Public symbol removed, renamed, or signature changed in an incompatible way | `getMatter(id)` → `getMatter(id, opts)` with new required arg | Required edit before merge |
| **Contract** | Response shape, schema field, status code, or error type changed | `Matter.dol` becomes `Matter.dateOfLoss` | Required edit before merge |
| **Additive** | New surface area was added that the doc page now misrepresents by omission | New optional field, new endpoint, new flag | Suggested edit, mergeable as-is |
| **Cosmetic** | Comment, internal rename, formatting | JSDoc reworded | Logged, no PR row |

The classifier's job is to *not waste editor time*. Cosmetic hits never reach the PR. Additive hits arrive as suggestions, not blockers. Breaking and Contract hits arrive with the offending line, the new shape, and a draft replacement the editor can accept, edit, or reject.

---

## What the PR looks like

One PR per run, opened against the docs repository's default branch from `sentinel/drift-<YYYY-MM-DD>`. Title and body follow a fixed template so editors can triage from the inbox.

```text
Title:  docs: drift reconciliation — 2026-05-20 (7 files, 3 breaking, 4 additive)

Body:
  ## Sentinel run 2026-05-20

  Reconciled against 12 merged PRs since 2026-05-19 13:00 UTC.

  ### Breaking (3)
  - docs/api/matters.md  ← stonewall#4412  Matter.dol renamed to Matter.dateOfLoss
  - docs/api/matters.md  ← stonewall#4418  getMatter signature gained required `scope`
  - docs/cli/search.md   ← stonewall#4421  --pattern flag removed in favor of --tag

  ### Additive (4)
  - docs/api/matters.md  ← stonewall#4415  new optional field Matter.holdReason
  - docs/api/emails.md   ← stonewall#4419  new endpoint POST /v1/emails/bulk
  - docs/cli/search.md   ← stonewall#4421  new --since flag
  - docs/portal/usage.md ← stonewall#4424  new "QC" tab in operator portal

  ### Run artifacts
  - drift report:   .sentinel/runs/2026-05-20/drift.md
  - PR manifest:    .sentinel/runs/2026-05-20/prs.jsonl
  - surface delta:  .sentinel/runs/2026-05-20/surface.jsonl

  Editor: please review the diff and merge, edit, or close. Watermark advances on merge.
```

Each commit in the PR is one logical change — one renamed field, one removed flag — so editors can revert at the granularity of the drift, not the granularity of the run.

---

## Operator surface

### Trigger schedule

| Mode | Trigger | Use |
| --- | --- | --- |
| **Scheduled** | `cron '0 13 * * *'` | Default. Runs once a day at 13:00 UTC. |
| **Manual** | `workflow_dispatch` with optional `since` | Backfill, debug, or re-run after editor cleanup. |
| **On-demand** | Repository dispatch event `sentinel:run` | Allows a release manager to fire Sentinel at the end of a release train. |

### State

Sentinel state lives at `.sentinel/state.json` in the docs repository:

```json
{
  "watermark": "2026-05-19T13:00:00Z",
  "last_run_id": "2026-05-19",
  "last_pr": "stonewall-docs/142",
  "last_pr_status": "merged",
  "consecutive_failures": 0
}
```

It is a single file by design. A reviewer auditing a Sentinel PR can read this file and reconstruct what the bot saw without leaving the repository.

### Config

`.sentinel/config.yml`:

```yaml
source_repo: your-org/platform-repo
docs_repo:   your-org/docs-repo
docs_paths:
  - docs/api/**
  - docs/cli/**
  - docs/overview/**
  - docs/portal/**.md
api_paths:
  - scripts/**.py
  - scripts/**.mjs
  - hoss-stonewall/**.py
editor_rota:
  - lead-docs-editor
labels: [docs-drift, sentinel, needs-editor]
classifier:
  model: claude-haiku-4-5-20251001
  temperature: 0.1
  max_tokens_per_hit: 600
fail_open: true
```

`fail_open: true` is deliberate. If Sentinel cannot run cleanly, it opens a tracking issue and yields control rather than opening a half-built PR. Editors never have to triage a drift PR they cannot trust.

---

## Why these design choices

### Daily, not per-merge

Per-merge would either spam editors or coalesce poorly. A daily rollup matches editor cadence, batches related changes (renames usually arrive in clusters), and gives the codebase a quiet window to settle.

### One rollup PR, not one PR per drift

Editors complete drift reviews in batches. A single PR with per-file commits is faster to review than ten PRs, easier to revert at the right granularity, and produces a single artifact in the docs changelog instead of ten.

### Watermark in the repo, not in a database

The watermark is one JSON file. Inspectable, version-controlled, conflict-resolvable with normal git tooling. If Sentinel ever has to be rebuilt from scratch, the watermark survives.

### Claude for suggested edits, not for the classifier

The classifier is deterministic and explainable — it is symbol diffing, not LLM intuition. Claude is used only to draft the replacement prose once a hit is confirmed, where its output is editor-reviewed before merge. The two-tier split keeps the bot trustworthy without giving up the writing leverage.

### Editor-merged, not auto-merged

Sentinel never merges its own PRs. Documentation tone, completeness, and judgment are editor work. Sentinel does the staging.

---

## Failure modes and recovery

| Failure | Sentinel behavior | Editor action |
| --- | --- | --- |
| Source repo unreachable | Run aborts. Watermark not advanced. Tracking issue opened. | Re-run via `workflow_dispatch` when network recovers. |
| No PRs merged since watermark | Run completes successfully with no PR. Watermark advances. | None. |
| Drift detected, classifier disagrees with itself across runs | Hit is downgraded to suggestion and logged as `unstable`. | Read the run artifact; decide if the rule needs tightening. |
| Editor closes the rollup PR without merging | Watermark does **not** advance. Next run will re-detect the same drift. | Either merge a follow-up PR or move the watermark by hand. |
| Sentinel opens a PR with no real drift | Open an issue with the run id; the classifier is over-broad on a path. | Tune `.sentinel/config.yml` exclusion rules. |

---

## Metrics that prove it is working

Sentinel writes a one-line append to `.sentinel/metrics.jsonl` on every run. The dashboard reads from there.

| Metric | What it measures | Why it matters |
| --- | --- | --- |
| `time_to_doc_reconciliation` | Hours between PR merge and Sentinel-detected drift | Should sit under 24h. If it climbs, the cron is missing runs. |
| `editor_accept_rate` | Fraction of Sentinel commits merged without edit | High rate = classifier is sharp. Low rate = drafts need tuning. |
| `false_positive_rate` | Fraction of Sentinel PRs closed without merge | The bot's trust score. Target under 5%. |
| `coverage` | Fraction of merged source PRs that produced *any* Sentinel verdict | Detects index decay — paths that stopped being scanned. |
| `streak_clean_runs` | Consecutive runs without a tracking issue | Operational health for the dashboard. |

---

## What it does **not** do

Naming the negative space is part of keeping a tool trustworthy.

- Sentinel does not edit documentation outside the docs repository.
- Sentinel does not rewrite tone, voice, or structure. It only stages content edits keyed to the contract change.
- Sentinel does not chase third-party API drift. It only watches repositories listed in `.sentinel/config.yml`.
- Sentinel does not merge. Editors merge.
- Sentinel does not promise zero false positives. It promises that every PR it opens carries the receipts to falsify it in under a minute.

---

## Status

| Item | State |
| --- | ---: |
| Documentation | Stable (this file) |
| Workflow | `.github/workflows/docs-drift-sentinel.yml` — scaffolding stage |
| Stage scripts | `scripts/sentinel/` — scaffolding stage |
| First production run | Targeted within the next release train |
| Owners | Showcase repository maintainers |

When Sentinel is doing its job, this page is the only place a new editor needs to read to understand what the bot is, what it will and will not touch, and how to override it.
