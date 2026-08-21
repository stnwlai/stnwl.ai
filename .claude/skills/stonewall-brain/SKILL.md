---
name: stonewall-brain
description: Legal document intelligence skill for case analysis, document classification, corpus synthesis, and matter status lookups across the Stonewall platform. Use when the user asks about case documents, email patterns, filing analysis, or wants synthesis from the document corpus.
---

# Document Intelligence Skill

Instant recall and synthesis for legal matter documents, email corpus analysis, and case status reporting.

## Core Capabilities

- **Document classification** — Identify type, parties, dates, and claim numbers
- **Case timeline construction** — Build chronological timelines from ingested documents
- **Email corpus analysis** — Surface patterns, gaps, and correspondence timelines
- **Matter synthesis** — Produce case summaries from multiple related documents
- **Gap analysis** — Identify missing documents or incomplete records

## Analysis Protocol

For each document or corpus query:

1. **Identify document type and parties** — What kind of document? Who are the principal actors?
2. **Extract key dates and deadlines** — Filed date, referenced dates, upcoming deadlines
3. **Identify case references** — Claim numbers, case names, matter linkage
4. **Surface gaps** — What's missing? What's inconsistent with the record?
5. **Synthesize context** — How does this document fit the broader case picture?

## Corpus Search

Before composing any analysis, search the available data:

1. **Check case index** — Use the current case/matter index tooling configured for this environment to retrieve matter metadata.
2. **Review case timeline** — Use the available timeline or docketing tools to understand key dates and procedural posture.
3. **Search email corpus** — Cross-reference for related correspondence and communication patterns.
4. **Consult Notion** — Legal Matters DB for current case status and high-level matter details.

Database IDs come from environment variables:
- Legal Matters: `NOTION_LEGAL_MATTERS_DB`
- All Email: `NOTION_ALL_EMAIL_DB`
- Document Archive: `NOTION_ARCHIVE_DB`

## Quality Bar

Before finalizing any answer:
- Verify at least one source path for material claims
- Do not fabricate dates, amounts, or case outcomes
- Flag when information is not found rather than guessing
- Keep output clear, specific, and anchored in actual documents
