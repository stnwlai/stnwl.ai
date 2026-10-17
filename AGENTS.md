# Repository Guide

## Scope

`stnwlai/stnwl.ai` is Stonewall's public marketing repository. The product and
real corpus belong in `stnwlai/stonewall`. Keep public copy short, factual,
and clear about that distinction.

The bundled evidence demo uses synthetic records to illustrate
content-addressed evidence, line-verifiable citations, explainable BM25
retrieval, a fail-closed publication boundary, grounded answers, speaker-bound
quotations, designation flow control, and checks that can fail. Describe these
as demo behavior, not as proof of the private product's capabilities.

`README.md` is the only narrative surface. Do not add a Pages site, portal,
archive mirror, product brief, operational runbook, integration sample, agent
configuration, or production architecture. No model calls, no network access,
no hosted surface. Keep private product code, corpus data, credentials, and
implementation details out of this repository.

## Commands

Run every check before opening or updating a pull request:

    PYTHONPATH=src python3 -m unittest discover -s tests -p "test_*.py"
    PYTHONPATH=src PYTHONHASHSEED=1 python3 -m stonewall build --output build/reference
    PYTHONPATH=src PYTHONHASHSEED=2 python3 -m stonewall verify --output build/reference
    PYTHONPATH=src python3 -m stonewall audit-answer examples/answers/grounded.md
    PYTHONPATH=src python3 -m stonewall transcripts --check README.md
    PYTHONPATH=src python3 scripts/check_public_boundary.py
    PYTHONPATH=src python3 -m stonewall checks

After edits, refresh in this order, review each diff, then rerun everything:

    PYTHONPATH=src python3 -m stonewall transcripts --write README.md
    PYTHONPATH=src python3 scripts/check_public_boundary.py --write-manifest

Generate transcripts with Python 3.12, the CI version.

## Change rules

- Standard library only; Python 3.12. 4-space indentation, type annotations,
  frozen slotted dataclasses, typed errors, canonical JSON, deterministic
  ordering.
- Corpus records carry `id`, `type`, `date`, and `designation`. Preserve
  coded IDs. Editing a record the answer's channel can see changes its
  evidence packet, so every answer written against that channel reports
  `packet_mismatch` by design; records above the channel's ceiling do not
  affect it. Refresh an answer's `packet:` line by hand, from
  `stonewall packet`, only when the change is intended.
- A check or audit rule is not done until a seeded defect or a pinned test
  proves it fails for its named rule. A check lands with its defects in the
  same change.
- Never delete, weaken, or retarget a seeded defect, an expected-failure
  answer, or `FIXED_DECISIONS` to make a run pass; fix the check. A defect
  that no longer applies is a fixture to update.
- If a check fails on an unmodified copy, repair the check in a separate
  change.
- Checks read; they never write. Build output goes to a scratch directory.
- Tests never run `stonewall checks` on this repository; harness tests build
  synthetic trees.
- Findings, errors, and reports carry rule ids, locations, handles,
  designations, and speaker labels. Never a quotation, figure, source text, or
  matched value.
- README ```console blocks are generated transcripts; use ```bash for
  instructions. Counts appear only in generated command output.
- Example data is synthetic and role-labelled: no personal, firm, tribunal, or
  vendor names; no phone, SSN, street-address, or non-example.com email
  shapes. The address detector reads a numeral followed within four words by
  "court", "place", or "way" as an address: write "tribunal" and rephrase.
  Split any seeded payload the scanner would reject into `parts`.
- Never end an identifier in token, secret, password, or api_key when it is
  assigned a value of 12 or more characters; use names such as `ref`.
- Never commit credentials, personal information, environment-specific paths,
  generated bundles, caches, or local reports.
- Treat manifest drift as a review requirement, not as a formatting chore.
- Keep the remote to `main` plus branches with open pull requests; delete
  merged branches.
