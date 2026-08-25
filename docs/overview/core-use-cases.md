# Core Legal Intelligence Use Cases

**Perspective:** Litigation team

This document defines the core user jobs, key workflows, and success criteria for Stonewall's legal intelligence product. The use cases model recurring work across a high-volume civil litigation docket. Each entry maps to a concrete workflow the platform must execute reliably for a litigation team.

---

## Use Case 1 — Daily Tactical Awareness

**Job to be done:** Start the working day with a complete, actionable picture of the docket in under two minutes.

### Workflow

1. Operator opens the platform CLI or Shelby chat surface.
2. Platform generates a morning dossier spanning all active matters: new documents ingested overnight, deadlines in the next 14 days, matters with changed posture since the last session, and open items without a next action.
3. Each matter posture summary links to the source artifacts that changed its status.
4. Operator reviews the dossier, identifies the highest-priority items, and routes tasks accordingly — either directly in Notion or by issuing a follow-up query.

### Success Criteria

- Dossier renders in under 10 seconds from the time the command or chat session opens.
- Every deadline surfaced in the dossier traces to a durable artifact or date record in the corpus — no unattributed warnings.
- Matter posture changes are delta-driven: the dossier flags what is genuinely new relative to the prior session, not a static full reload.
- The operator can reach a matter's full artifact timeline in one additional command or click from the dossier.

---

## Use Case 2 — Matter Corpus Search

**Job to be done:** Locate every artifact relevant to a specific matter, claim, or counterparty within 30 seconds of forming the query.

### Workflow

1. Operator issues a search query — by matter name, claim number, party, date range, or artifact type — through the CLI (`find`, `case`) or Shelby chat.
2. Platform resolves the query against the indexed corpus, matching by entity references, claim identifiers, and matter linkages.
3. Results return ranked artifacts with artifact type, date, and summary — sufficient for triage without opening each file.
4. Operator promotes relevant artifacts to a working set for the active task (deposition prep, chronology assembly, motion drafting).

### Success Criteria

- Claim numbers resolve to matter pages across every carrier format in the corpus without requiring exact-string precision.
- Search across 500+ artifacts returns ranked results in under 5 seconds.
- Every result references a verifiable file path in the archive — no hallucinated citations.
- The platform's entity and citation schema contract is the ground truth for result attribution.

---

## Use Case 3 — Deposition Preparation

**Job to be done:** Walk into a deposition with a live, corpus-backed outline that can be tightened in real time as testimony unfolds.

### Workflow

1. Operator identifies the upcoming witness and associated matter.
2. Platform assembles a witness profile from the corpus: prior statements, emails naming the witness, treatment or incident timeline, contradictions logged in behavioral patterns, and any open chronology gaps.
3. Operator reviews the profile and constructs or imports an outline; the platform annotates each outline section with the artifacts that support it.
4. During the deposition, the operator issues live queries ("find anything contradicting the October statement") without leaving the outline surface; results attach to the active section.
5. After the session, the updated outline and any new annotations are committed to the corpus as a deposition artifact.

### Success Criteria

- Witness profile assembly takes under 60 seconds from matter identification to rendered output.
- Live queries during testimony return in under 8 seconds — fast enough to be useful in the room.
- No outline section goes unsourced: every assertion in the platform-generated profile is backed by a specific artifact with date and type.
- Post-deposition artifact commit does not require manual re-tagging; the platform infers matter link and type from context.

---

## Use Case 4 — Packet Readiness and DataGavel Staging

**Job to be done:** Hand off a fully staged litigation packet — chronology, treatment trail, damages notes — to a downstream specialist without a reconstruction session.

### Workflow

1. Operator opens a matter's packet readiness view.
2. Platform reports what is present and what is missing across the four packet components: chronology of events, treatment or incident record, damages documentation, and correspondence log.
3. Operator resolves gaps by ingesting missing documents or flagging items for outside counsel to produce.
4. When all four components reach threshold completeness, the platform marks the matter as packet-ready.
5. Operator exports a staged summary document or hands off the DataGavel feed directly.

### Success Criteria

- Completeness percentage for each component is computed from the corpus, not from a manual tracker.
- A gap in any component surfaces as a specific actionable item ("no treatment record for the 2024-03-15 incident") not a generic flag.
- Packet-ready threshold is configurable per matter type without code changes.
- Export renders a print-ready summary in under 30 seconds.

---

## Use Case 5 — Deadline and Runway Intelligence

**Job to be done:** Know which deadlines are live, which have documentary or workflow risk attached, and which have enough runway to defer.

### Workflow

1. Platform maintains a consolidated deadline timeline across all active matters, populated from corpus date fields, Notion sync, and manually entered statute-of-limitations and court-ordered dates.
2. Operator views deadlines in a 90-day rolling window, grouped by matter and color-coded by runway: urgent (≤7 days), proximate (8–30 days), and planning (31–90 days).
3. For each deadline, the platform attaches the workflow dependencies that determine whether the matter is ready: outstanding packet components, pending productions, unverified treatment records.
4. Operator identifies deadlines with dependency risk and routes mitigation tasks.

### Success Criteria

- Timeline reflects corpus date changes within one sync cycle — no manual refresh required after ingestion.
- Every deadline entry displays at least one associated artifact or dependency item; orphan dates are flagged automatically.
- Operator can filter the timeline by matter, deadline type, or risk level without leaving the surface.
- A deadline with zero open dependencies is visually distinct from one with unresolved gaps.

---

## Use Case 6 — Shelby Chat Intelligence Layer

**Job to be done:** Ask the platform a natural-language question about any matter and receive a sourced, trustworthy answer without running a custom query.

### Workflow

1. Operator opens the Shelby chat surface.
2. Operator poses a question: "What is the current posture on matter M0004?" or "Which matters have a statute of limitations expiring before October?"
3. Shelby resolves the question through routed recall: it identifies the relevant codex files and corpus sections, reads them fresh, then synthesizes a response with inline source citations.
4. Operator follows a citation to the underlying artifact in one click.
5. If Shelby cannot answer with confidence from the corpus, it says so — and identifies what additional ingestion would close the gap.

### Success Criteria

- Every factual claim in a Shelby response cites a specific artifact (file path, date, type) in the current corpus.
- Shelby does not assert facts it cannot source; refusal with a clear gap description is a passing behavior, not a failure.
- Response latency for corpus-backed answers is under 15 seconds.
- Operators can launch a targeted ingestion task from within the chat surface when Shelby identifies a missing source.

---

## Cross-Workflow Requirements

These requirements apply to all six use cases and define the shared platform baseline.

| Requirement | Rationale |
| --- | --- |
| Every assertion traces to a corpus artifact | Eliminates unverifiable output across all surfaces |
| The platform schema contract governs entity and citation normalization | Ensures consistent identity resolution for parties, matters, and dates |
| All sync operations are idempotent | Running a workflow twice produces the same result; no duplicate artifacts |
| Rate-limited external calls include exponential-backoff retry | Notion and AI providers rate-limit; the platform must not fail silently under load |
| CLI and Shelby produce consistent results for the same query | Operator trust depends on determinism across surfaces |

---

## North-Star Metrics

| Metric | Target |
| --- | --- |
| Daily dossier generation time | ≤ 10 seconds |
| Matter corpus search latency | ≤ 5 seconds for 500+ artifacts |
| Deposition witness profile assembly | ≤ 60 seconds |
| Packet readiness export | ≤ 30 seconds |
| Shelby sourced-response latency | ≤ 15 seconds |
| Unsourced assertions in Shelby output | 0 |

---

## Open Questions

1. **Schema handshake** — Entity normalization and the citation schema must be finalized before Use Cases 2 and 6 can enforce zero-hallucination guarantees. Blocking dependency.
2. **Packet readiness thresholds** — What constitutes minimum viable completeness for each matter type (auto accident, premises liability, product liability) must be codified as configuration before Use Case 4 is production-ready.
3. **Deposition live query latency** — The 8-second target for in-room queries (Use Case 3) may require a separate low-latency retrieval path. Evaluate against corpus size at the 500-artifact mark.
4. **Shelby refusal UX** — How Shelby presents a confident refusal (corpus gap identified) vs. a degraded-confidence response must be specified before the chat surface ships to a second operator.
