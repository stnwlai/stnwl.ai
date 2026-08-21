#!/usr/bin/env python3
"""Generate the showcase corpus.

Produces 78 working artifacts across eight categories — cases, depositions,
transcripts, emails, motions, characters, patterns, and billing — that
exercise the Stonewall ingest, classification, manifest, and verification
surfaces end-to-end.

Run from anywhere; paths are repo-relative.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "hoss-stonewall" / "sample_corpus"

CASE_COUNT = 12

PLAINTIFFS = [
    "Smith", "Jones", "Doe", "Roe", "Brown", "Davis", "Wilson", "Taylor",
    "Anderson", "Thomas", "Jackson", "White", "Harris", "Martin", "Thompson",
    "Garcia", "Martinez", "Robinson", "Clark", "Rodriguez",
]
DEFENDANTS = [
    "Acme Corp", "Globex Logistics", "Initech Freight", "Umbrella Shipping",
    "Soylent Transport", "Vehement Capital", "Massive Dynamic", "Tyrell Group",
    "Cyberdyne Carriers", "Wayne Logistics", "Hooli Transport", "Pied Piper Co",
    "Wonka Industries", "Dunder Mifflin", "Stark Industries", "Aperture Hauling",
    "Octan Freight", "Krusty Co", "Strickland Propane", "Bluth Company",
]


def slug(text: str) -> str:
    return text.lower().replace(" ", "_").replace(",", "").replace(".", "")


def matter_id(idx: int) -> str:
    return f"M{idx:04d}"


def case_matter(idx: int) -> str:
    """Caption of case matter M{idx:04d}."""
    plaintiff = PLAINTIFFS[idx % len(PLAINTIFFS)]
    defendant = DEFENDANTS[(idx * 3) % len(DEFENDANTS)]
    return f"{plaintiff} v. {defendant}"


def linked_case_index(idx: int) -> int:
    """Cycle non-case artifacts through the case matters so every artifact
    references a matter that exists in the corpus."""
    return (idx - 1) % CASE_COUNT + 1


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not content.endswith("\n"):
        content += "\n"
    path.write_text(content, encoding="utf-8")


def make_case(idx: int) -> None:
    mid = matter_id(idx)
    name = case_matter(idx)
    body = f"""---
id: {mid}
type: case
matter: {name}
status: active
opened: 2025-{(idx % 12) + 1:02d}-{(idx % 27) + 1:02d}
---

# {name}

## Posture

Discovery phase. Plaintiff alleges a commercial vehicle incident; defendant
has answered and demanded jury trial. The matter sits in the active runway
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
    write(ROOT / "cases" / f"{mid}_{slug(name)}.md", body)


def make_deposition(idx: int) -> None:
    did = f"D{idx:04d}"
    name = case_matter(linked_case_index(idx))
    body = f"""---
id: {did}
type: deposition
matter: {name}
witness: Witness {idx:03d}
date: 2025-{(idx % 12) + 1:02d}-{(idx % 27) + 1:02d}
---

# Deposition Outline — {name}

## Background

1. Confirm name and current employer.
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
    name = case_matter(linked_case_index(idx))
    body = f"""---
id: {tid}
type: transcript
matter: {name}
forum: Status Conference
date: 2025-{(idx % 12) + 1:02d}-{(idx % 27) + 1:02d}
---

# Status Conference Transcript — {name}

THE COURT: We are on the record in matter {tid}. Counsel, please state
your appearances for the record.

MR. ATTORNEY (for Plaintiff): Good morning, Your Honor.

MS. ATTORNEY (for Defendant): Good morning, Your Honor.

THE COURT: The court has reviewed the joint status report. We will
schedule a follow-up status in sixty days.

(Proceedings concluded.)

Transcript {tid}.
"""
    write(ROOT / "transcripts" / f"{tid}_status.md", body)


def make_email(idx: int) -> None:
    eid = f"E{idx:04d}"
    name = case_matter(linked_case_index(idx))
    body = f"""---
id: {eid}
type: email
matter: {name}
direction: outbound
date: 2025-{(idx % 12) + 1:02d}-{(idx % 27) + 1:02d}
---

# Email — Discovery Status

Subject: {name} — Discovery Update

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
    name = case_matter(linked_case_index(idx))
    body = f"""---
id: {mid}
type: motion
matter: {name}
filing: Motion to Compel
date: 2025-{(idx % 12) + 1:02d}-{(idx % 27) + 1:02d}
---

# Motion to Compel

## Introduction

Plaintiff respectfully moves the Court for an order compelling Defendant to
produce documents responsive to Requests for Production Nos. 1 through 12,
served on a date previously agreed by the parties.

## Argument

The requested documents are relevant under Rule 26 and proportionate to the
needs of the case. Defendant has not asserted privilege with specificity.

## Conclusion

For the reasons stated above, Plaintiff respectfully requests an order
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
role: {role}
---

# Character Card — {role} {idx:03d}

## Role

{role} appearing in commercial litigation matters. Tracked across the
portfolio for cast-codex routing and pattern analysis.

## Pattern Tags

- ROLE_BASELINE
- COMMUNICATION_STANDARD
- DOCUMENT_DISCIPLINE

Card {cid}.
"""
    write(ROOT / "characters" / f"{cid}_role_{slug(role)}.md", body)


def make_pattern(idx: int) -> None:
    pid = f"P{idx:04d}"
    name = [
        "STALL_AND_DELAY", "OVERPRODUCE_TO_BURY", "PRIVILEGE_SHIELD_DRIFT",
        "CALENDAR_GAMING", "WITNESS_SHUFFLE", "DOCUMENT_HOLD_LATE",
        "DEADLINE_CREEP", "MEET_AND_CONFER_FORMALISM",
    ][idx % 8]
    body = f"""---
id: {pid}
type: pattern
name: {name}
---

# Pattern — {name}

## Definition

A recurring behavior observed in routine commercial defense practice that
warrants tracking across matters. Captured here as a registry entry that
the phenomenology layer can attach to incoming artifacts.

## Counter-Move

Document the behavior, raise it on the record, and convert it to a runway
event for the next status conference.

Pattern {pid}.
"""
    write(ROOT / "patterns" / f"{pid}_{slug(name)}.md", body)


def make_billing(idx: int) -> None:
    bid = f"B{idx:04d}"
    name = case_matter(linked_case_index(idx))
    body = f"""---
id: {bid}
type: billing
matter: {name}
period: 2025-{(idx % 12) + 1:02d}
---

# Billing — {name}

| Date       | Task                          | Hours | Rate  | Amount  |
|------------|-------------------------------|-------|-------|---------|
| 2025-{(idx % 12) + 1:02d}-04 | Review correspondence         | 0.4   | 350   | 140.00  |
| 2025-{(idx % 12) + 1:02d}-09 | Draft discovery responses     | 2.1   | 350   | 735.00  |
| 2025-{(idx % 12) + 1:02d}-16 | Witness preparation outline   | 1.8   | 350   | 630.00  |
| 2025-{(idx % 12) + 1:02d}-23 | Status conference attendance  | 0.7   | 350   | 245.00  |

Statement {bid}.
"""
    write(ROOT / "billing" / f"{bid}_period.md", body)


def main() -> None:
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
    total = 0
    for kind, n in counts.items():
        for i in range(1, n + 1):
            makers[kind](i)
            total += 1
    print(f"Wrote {total} artifacts across {len(counts)} categories.")


if __name__ == "__main__":
    main()
