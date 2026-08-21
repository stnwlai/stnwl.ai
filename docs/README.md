# docs

Public documentation surface for the Stonewall showcase repository.

## Overview narratives

Long-form product and engineering documentation lives in [`overview/`](overview/).

| Document | Reads as |
| --- | --- |
| [`overview/official-brief.md`](overview/official-brief.md) | Canonical product thesis. |
| [`overview/core-use-cases.md`](overview/core-use-cases.md) | The six operator jobs the platform must execute reliably, with workflows and success criteria. |
| [`overview/product-architecture.md`](overview/product-architecture.md) | How the corpus, indexes, CLI, AI, workflow, and publication layers fit together. |
| [`overview/workflow-surfaces.md`](overview/workflow-surfaces.md) | Where the archive becomes operator leverage. |
| [`overview/docs-drift-watcher.md`](overview/docs-drift-watcher.md) | Technical reference for the scheduled drift watcher (workflow, scanner, banners, config). |
| [`overview/docs-drift-sentinel.md`](overview/docs-drift-sentinel.md) | Design rationale and operating model for the drift-reconciliation routine. |

## Showcase narratives

Engineering-exhibit narratives live in [`showcase/`](showcase/).

| Document | Reads as |
| --- | --- |
| [`showcase/docs-drift-watcher.md`](showcase/docs-drift-watcher.md) | Flagship narrative — the daily routine that keeps docs honest about the code, with day-in-the-life, editor surface, and proof points. |
| [`showcase/stonewall-showcase.md`](showcase/stonewall-showcase.md) | Showcase entrypoint and companion-surface map. |
| [`showcase/synergy-v13.md`](showcase/synergy-v13.md) | Cross-layer synergy narrative. |

## Operator portal

The static operator surface lives in [`portal/`](portal/). Data snapshots are under `portal/data/*.json`.

## Publication policy

| Document | Covers |
| --- | --- |
| [`public-content-policy.md`](public-content-policy.md) | JSON-backed metrics — bindings, not pinned counts |
| [`repository-presentation-policy.md`](repository-presentation-policy.md) | Branch hygiene, naming, and fundable repo presentation |

## Architecture reference

[`ARCHITECTURE.md`](ARCHITECTURE.md) is the engineering-grade architecture diagram of the full automation platform.
