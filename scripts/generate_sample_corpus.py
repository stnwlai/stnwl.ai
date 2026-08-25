#!/usr/bin/env python3
"""Generate the showcase corpus.

Produces 78 coded artifacts across eight categories — cases, depositions,
transcripts, emails, motions, characters, patterns, and billing — that
exercise the Stonewall compilation, retrieval, citation, and
verification surfaces end-to-end.

Run from anywhere; paths are repo-relative.
"""
from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "hoss-stonewall" / "sample_corpus"

CASE_COUNT = 12
CATEGORIES = (
    "cases",
    "depositions",
    "transcripts",
    "emails",
    "motions",
    "characters",
    "patterns",
    "billing",
)


def slug(text: str) -> str:
    return text.lower().replace(" ", "_").replace(",", "").replace(".", "")


def matter_id(idx: int) -> str:
    return f"M{idx:04d}"


def matter_title(idx: int) -> str:
    return f"Matter {matter_id(idx)} — Commercial Transport"


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not content.endswith("\n"):
        content += "\n"
    path.write_text(content, encoding="utf-8")


def clear_generated_artifacts(root: Path = ROOT) -> None:
    """Remove only generator-owned Markdown records before a full rebuild."""
    resolved_root = root.resolve()
    if resolved_root.name != "sample_corpus" or resolved_root.parent.name != "hoss-stonewall":
        raise RuntimeError(f"refusing to clear unexpected corpus root: {resolved_root}")
    for category in CATEGORIES:
        category_root = resolved_root / category
        if not category_root.is_dir():
            continue
        for path in category_root.glob("*.md"):
            path.unlink()


def make_case(idx: int) -> None:
    mid = matter_id(idx)
    title = matter_title(idx)
    body = f"""---
id: {mid}
type: case
date: 2025-{(idx % 12) + 1:02d}-{(idx % 27) + 1:02d}
---

# {title}

## Posture

Discovery phase. Claimant Role A alleges a commercial vehicle event;
Organization Role B has answered and requested trial. The matter sits in the active runway
with discovery requests outstanding and the deposition window opening next
quarter.

## Key Dates

- Filed: 2025-{(idx % 12) + 1:02d}-{(idx % 27) + 1:02d}
- Answer due: see runway lane
- Discovery cutoff: rolling

## Pattern Tags

- ROUTINE_COMMERCIAL
- DISCOVERY_SCHEDULED
- WITNESS_LIST_PENDING

## Notes

Matter {mid}.
"""
    write(ROOT / "cases" / f"{mid}_commercial_transport.md", body)


def make_deposition(idx: int) -> None:
    did = f"D{idx:04d}"
    body = f"""---
id: {did}
type: deposition
date: 2025-{(idx % 12) + 1:02d}-{(idx % 27) + 1:02d}
---

# Deposition Plan {did}

## Background

1. Confirm the witness role and organizational relationship.
2. Confirm role at the time of the underlying event.
3. Walk through training history at a high level.

## The Event

1. Pre-trip inspection routine.
2. Route selection and time of departure.
3. First awareness of the incident.

## Post-Event

1. Reporting chain.
2. Documents prepared.
3. Communications with supervisors.

## Pattern Anchors

- WITNESS_PREP_BASELINE
- TIMELINE_CONFIRMED
- DOCUMENT_HOLD_REVIEWED

Outline {did}.
"""
    write(ROOT / "depositions" / f"{did}_outline.md", body)


def make_transcript(idx: int) -> None:
    tid = f"T{idx:04d}"
    body = f"""---
id: {tid}
type: transcript
date: 2025-{(idx % 12) + 1:02d}-{(idx % 27) + 1:02d}
---

# Status Conference Transcript {tid}

PRESIDING OFFICIAL: We are on the record in coded proceeding {tid}. Counsel roles,
please state your appearances for the record.

COUNSEL ROLE A: Good morning.

COUNSEL ROLE B: Good morning.

PRESIDING OFFICIAL: The tribunal has reviewed the joint status report. We will
schedule a follow-up status in sixty days.

(Proceedings concluded.)

Transcript {tid}.
"""
    write(ROOT / "transcripts" / f"{tid}_status.md", body)


def make_email(idx: int) -> None:
    eid = f"E{idx:04d}"
    body = f"""---
id: {eid}
type: email
date: 2025-{(idx % 12) + 1:02d}-{(idx % 27) + 1:02d}
---

# Communication Record {eid} — Discovery Status

Subject: Communication {eid} — Discovery Update

Counsel,

Confirming receipt of your responses dated last week. We will circulate
proposed deposition dates by end of next week. Please let us know if any
witness scheduling conflicts have changed since our last meet-and-confer.

Best regards,
Counsel of Record

Email {eid}.
"""
    write(ROOT / "emails" / f"{eid}_discovery_update.md", body)


def make_motion(idx: int) -> None:
    mid = f"X{idx:04d}"
    body = f"""---
id: {mid}
type: motion
date: 2025-{(idx % 12) + 1:02d}-{(idx % 27) + 1:02d}
---

# Motion to Compel

## Introduction

Party Role A respectfully moves the tribunal for an order compelling Party Role B to
produce documents responsive to Requests for Production Nos. 1 through 12,
served on a date previously agreed by the parties.

## Argument

The requested documents are relevant under the governing discovery rule and
proportionate to the needs of the matter. Party Role B has not stated an
objection with specificity.

## Conclusion

For the reasons stated above, Party Role A respectfully requests an order
compelling production within fourteen days of entry.

Motion {mid}.
"""
    write(ROOT / "motions" / f"{mid}_motion_to_compel.md", body)


def make_character(idx: int) -> None:
    cid = f"C{idx:04d}"
    role = ["Adjuster", "Defense Counsel", "Witness", "Expert", "Investigator"][idx % 5]
    body = f"""---
id: {cid}
type: character
date: 2025-{(idx % 12) + 1:02d}-{(idx % 27) + 1:02d}
---

# Actor Card {cid} — {role} Role

## Role

{role} vocabulary record used to exercise deterministic retrieval and citation
verification across the reference corpus.

## Pattern Tags

- ROLE_BASELINE
- COMMUNICATION_STANDARD
- DOCUMENT_DISCIPLINE

Card {cid}.
"""
    write(ROOT / "characters" / f"{cid}_role_{slug(role)}.md", body)


def make_pattern(idx: int) -> None:
    pid = f"P{idx:04d}"
    name = f"PROCEDURE_SIGNAL_{idx:02d}"
    body = f"""---
id: {pid}
type: pattern
date: 2025-{(idx % 12) + 1:02d}-{(idx % 27) + 1:02d}
---

# Pattern — {name}

## Definition

A neutral procedure signal used to exercise exact-term retrieval, heading
weighting, and line-verifiable citations.

## Counter-Move

Review the cited source span and record the next procedural step.

Pattern {pid}.
"""
    write(ROOT / "patterns" / f"{pid}_{slug(name)}.md", body)


def make_billing(idx: int) -> None:
    bid = f"B{idx:04d}"
    body = f"""---
id: {bid}
type: billing
date: 2025-{(idx % 12) + 1:02d}-01
---

# Billing Record {bid}

| Date       | Task                          | Hours | Rate  | Amount  |
|------------|-------------------------------|-------|-------|---------|
| 2025-{(idx % 12) + 1:02d}-04 | Review correspondence         | 0.4   | 350   | 140.00  |
| 2025-{(idx % 12) + 1:02d}-09 | Draft discovery responses     | 2.1   | 350   | 735.00  |
| 2025-{(idx % 12) + 1:02d}-16 | Witness preparation outline   | 1.8   | 350   | 630.00  |
| 2025-{(idx % 12) + 1:02d}-23 | Status conference attendance  | 0.7   | 350   | 245.00  |

Statement {bid}.
"""
    write(ROOT / "billing" / f"{bid}_period.md", body)


def generate(root: Path = ROOT) -> int:
    global ROOT
    previous_root = ROOT
    ROOT = root
    counts = {
        "case": CASE_COUNT,
        "deposition": 10,
        "transcript": 8,
        "email": 14,
        "motion": 10,
        "character": 10,
        "pattern": 8,
        "billing": 6,
    }
    makers = {
        "case": make_case,
        "deposition": make_deposition,
        "transcript": make_transcript,
        "email": make_email,
        "motion": make_motion,
        "character": make_character,
        "pattern": make_pattern,
        "billing": make_billing,
    }
    try:
        clear_generated_artifacts(root)
        total = 0
        for kind, n in counts.items():
            for i in range(1, n + 1):
                makers[kind](i)
                total += 1
        return total
    finally:
        ROOT = previous_root


def artifact_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for category in CATEGORIES
        for path in sorted((root / category).glob("*.md"))
    }


def check_generated() -> int:
    with tempfile.TemporaryDirectory(prefix="stonewall-reference-") as raw:
        candidate = Path(raw) / "hoss-stonewall" / "sample_corpus"
        generate(candidate)
        expected = artifact_bytes(candidate)
    actual = artifact_bytes(ROOT)
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        changed = sorted(
            path for path in set(actual) & set(expected) if actual[path] != expected[path]
        )
        print(
            "Reference corpus differs from its generator: "
            f"missing={len(missing)}, unexpected={len(unexpected)}, changed={len(changed)}"
        )
        return 1
    print(f"Reference corpus is deterministic: {len(actual)} artifacts.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    if args.check:
        return check_generated()
    total = generate(args.output)
    print(f"Wrote {total} artifacts across {len(CATEGORIES)} categories.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
