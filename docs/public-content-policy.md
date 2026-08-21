# Public Content Policy

This document defines how publication surfaces in the Stonewall showcase repository bind to data. It applies to every visitor-facing page under `docs/`, the root `README.md`, and any companion surface listed in the publication runbook.

## Purpose

Public pages must present aggregates sourced from checked-in JSON snapshots. Hand-entered counts in HTML, Markdown, or narrative copy drift from the corpus within days and undermine trust in the platform's validation story.

The policy has two goals:

1. **Single source of truth** — every number a visitor sees traces to a named field in a version-controlled JSON file.
2. **No stale literals** — policy and runbook text describe bindings and procedures, not pinned metric values.

Copy and tone rules for publication surfaces live in [`AGENTS.md`](../AGENTS.md) (Showcase Voice & PR Standards). This document covers data binding only.

## Scope

These surfaces are in scope:

| Surface | Primary data binding |
| --- | --- |
| `docs/index.html` | `docs/site-data.json` (client-side fetch) |
| `docs/portal/` | `docs/portal/data/*.json` (client-side fetch) |
| `docs/official-brief.html` | Must stay aligned with brief markdown and JSON snapshots |
| Root `README.md` | Must stay aligned with `docs/site-data.json` headline metrics |
| Any new metric-bearing publication page under `docs/` | Must declare its JSON source in this file before merge |

> **Static Markdown surfaces** (`README.md` and brief markdown) cannot fetch at runtime, so they mirror — rather than dynamically render — the JSON snapshots. Their headline metrics may only be changed as part of the same commit that updates the JSON field they mirror, and must match that snapshot at merge. The "Must not" hand-enter rule below prohibits counts that have no JSON source or that diverge from it — not the act of keeping a mirror aligned with its JSON during that workflow.

## Requirements

### Must

- Render aggregate counts from the canonical JSON files cited in the binding table below.
- Update JSON snapshots when the underlying corpus, manifest, or test suite changes.
- Keep `docs/site-data.json` and `docs/portal/data/metrics.json` aligned on overlapping fields before publishing.
- Run `python3 scripts/check_showcase_voice.py` before opening a PR that touches publication surfaces.

### Must not

- Hand-enter public counts in HTML, Markdown, or README copy when a JSON binding exists for that metric.
- Pin literal metric values, brain versions, or test-suite totals in policy docs, runbooks, or architecture narratives. Those values belong in JSON only.
- Introduce a second unpublished source of truth (spreadsheet, comment block, or inline script constant) for metrics that already have a JSON field.

Static HTML may include placeholder text for first paint, but runtime scripts must overwrite placeholders from JSON. If fetch fails, the page should degrade gracefully rather than presenting stale literals as authoritative.

## Canonical sources

### Homepage aggregate snapshot

**File:** `docs/site-data.json`

The showcase homepage (`docs/index.html`) fetches this file at load time. The `generated` timestamp records when the snapshot was last refreshed.

### Portal dashboard snapshot

**Directory:** `docs/portal/data/`

The portal loads eight JSON files in parallel (`metrics.json`, `cases.json`, `deadlines.json`, `artifacts.json`, `playbooks.json`, `patterns.json`, `cast.json`, `billing.json`). Dashboard tiles read from `metrics.json`.

## Metric bindings

Use this table to locate the authoritative field for each public aggregate. Values change as the corpus grows; the binding does not.

| Visitor-facing label | Canonical file | JSON path |
| --- | --- | --- |
| Artifacts cataloged | `docs/site-data.json` | `manifest.total_rows` |
| Active matters | `docs/site-data.json` | `cases.total_unique` |
| Behavioral patterns | `docs/site-data.json` | `patterns.total` |
| Character profiles | `docs/site-data.json` | `characters.total_unique` |
| Emails processed | `docs/site-data.json` | `showcase_metrics.emails_processed` |
| Artifact classes | `docs/site-data.json` | `showcase_metrics.artifact_classes` |
| Analyzed share | `docs/site-data.json` | `manifest.analysis_rate` |
| Validation errors / warnings | `docs/site-data.json` | `validation.errors`, `validation.warnings` |
| Brain codex version | `docs/site-data.json` | `brain.version` |
| Verification suite total | `docs/site-data.json` | `test_suite.total` |
| Portal cataloged artifacts | `docs/portal/data/metrics.json` | `cataloged_artifacts` |
| Portal active matters | `docs/portal/data/metrics.json` | `active_matters` |
| Portal pattern tags | `docs/portal/data/metrics.json` | `pattern_tags` |
| Portal runway / packet counters | `docs/portal/data/metrics.json` | `urgent_runway`, `packets_ready`, `live_threads` |

When a metric appears on more than one surface, all surfaces must read the same field (directly or by keeping both JSON files synchronized during publication).

## Update workflow

1. Refresh the underlying corpus or manifest (ingestion, validation, or test run as appropriate).
2. Update `docs/site-data.json` and any affected `docs/portal/data/*.json` files together.
3. Set `generated` in `docs/site-data.json` to the refresh timestamp.
4. Open the homepage and portal locally; confirm counters match the JSON on disk.
5. Run the publication checklist in [`showcase-repo-handoff.md`](showcase-repo-handoff.md).

Do not edit visitor-facing count text in HTML or Markdown when the JSON binding already exists. Edit the JSON, then verify the page renders it.

## Verification

Before calling a publication change complete:

```bash
python3 scripts/check_showcase_voice.py
python3 scripts/verify_repo_consistency.py
```

Manual checks:

- [ ] Homepage stat tiles match `docs/site-data.json` after JavaScript load
- [ ] Portal dashboard tiles match `docs/portal/data/metrics.json`
- [ ] No new hand-entered counts appear in publication HTML or README
- [ ] `docs/site-data.json` `generated` timestamp reflects the refresh

CI runs the showcase voice guard on every push (`.github/workflows/verify.yml`). A failed lint blocks merge.

## Related documents

| Document | Role |
| --- | --- |
| [`AGENTS.md`](../AGENTS.md) | Showcase voice rules and banned phrasing |
| [`showcase-repo-handoff.md`](showcase-repo-handoff.md) | Publication workflow and release checklist |
| [`overview/product-architecture.md`](overview/product-architecture.md) | Architecture diagram including JSON snapshot layer |
| [`repository-presentation-policy.md`](repository-presentation-policy.md) | Branch hygiene and fundable repo presentation |
| [`.github/copilot-instructions.md`](../.github/copilot-instructions.md) | Copilot guidance mirroring showcase voice rules |
