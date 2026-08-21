# Product Architecture

Stonewall is built on a deliberately simple premise: the archive should be the platform substrate.

That means the same underlying corpus can drive search, validation, workflow routing, AI recall, publication, and operator visibility without requiring a heavyweight database or a hidden orchestration layer.

## Core Layers

### Flat-file corpus layer

At the center of Stonewall is a durable manifest-driven corpus. Every artifact receives a stable ID, date, type, matter link, entity references, pattern references, and summary metadata. That creates a source of truth that remains inspectable and version-controlled.

### Index layer

Derivative indexes by character, matter, date, pattern, and email transform the corpus from a pile of files into something navigable under pressure.

### CLI layer

The CLI makes the archive operational. Search, stats, timelines, matter views, and validation all happen from one portable interface with zero external dependencies.

### AI recall layer

The AI brain is routed recall, not opaque memory. Codex files tell the model where to look, then require fresh reading before assertion.

### Workflow layer

Notion, packet readiness workflows, and witness-prep loops sit on top of the corpus rather than beside it. That keeps the archive and the operating layer synchronized.

### Publication layer

GitHub Pages, the portal, the official brief, and GitBook all express the same system through different presentation surfaces.

## Why the Architecture Matters

The architecture matters because coherence compounds. When search, validation, publication, and workflow all depend on the same structured substrate, the system becomes easier to trust, easier to maintain, and easier to extend.

Stonewall is not trying to hide complexity behind abstraction. It is trying to make complexity usable.

## Architecture Diagram

```text
OneDrive / Source Reservoir
            |
            v
      Ingestion Layer
  ingest_onedrive.py
  transcribe_repo_pdfs.py
  docx_to_verbatim_md.py
            |
            v
      Processing Layer
  sidecars / normalization / tagging
            |
            v
        Notion Sync
  notion_wire_cases.py
  notion_wire_batch.py
  notion_case_dates.py
            |
            v
         Catalog Layer
  manifest.md + derivative indexes
            |
            v
          CLI Query
  stats / find / case / pattern / timeline
            |
            v
        Static Portal
  site-data.json + docs/portal/data/*.json
```
