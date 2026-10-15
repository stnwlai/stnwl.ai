# Stonewall Evidence Reference

An answer cannot cite what retrieval did not return.

[![Verify](https://github.com/stnwlai/stnwl.ai/actions/workflows/verify.yml/badge.svg)](https://github.com/stnwlai/stnwl.ai/actions/workflows/verify.yml)

Courts have sanctioned lawyers for filings that cite authority that does not
exist and quote words no record contains. That is not a prompt problem; it is
a system that let an unverifiable sentence out the door. This repository is
the runnable reference, over a synthetic record and in standard-library
Python, for contracts in which every claim resolves to an artifact ID and a
source path, with line ranges where required.

Legal AI fails in three ways that matter:

- a sentence cites something nobody retrieved;
- a sentence quotes words nobody said, or words someone else said;
- privileged material ends up somewhere it may not go.

Here each of those is a nonzero exit code, and every check that enforces them
is itself proven able to fail.

Stonewall is a private working application for finding, reading, and reasoning
from a complete legal record, with a curated public site at
[stnwl.ai](https://stnwl.ai). This repository is not the product. It
demonstrates the kind of guarantees the product is built around, not how the
product is built, and it carries no operational code, data, or configuration.

## Sixty seconds

Every `console` block below is regenerated and compared by CI. Run them from
the repository root after setting this alias:

```bash
alias stonewall='PYTHONPATH=src python3 -m stonewall'
```

**1. The record.** A deposition excerpt, addressed by ID and line range. Line
14 is counsel's question; line 15 is the witness's answer. The span is re-read
and re-hashed before it is printed.

```console
$ stonewall cite T0002:12-15
T0002:12-15@c85b86f76176  transcripts/T0002_custody.md  public
  12  EXAMINING COUNSEL: Where was the original binder kept during March?
  13  THE WITNESS: In the records room. I kept a working copy at my desk.
  14  EXAMINING COUNSEL: So the original never left the records room?
  15  THE WITNESS: It left once. I signed it out on March 3 and returned it on March 5.
```

**2. What a model may receive.** The evidence packet for one question on the
`model` channel. Handles S1 to S4 are what an answer may cite. S4 is
confidential, which the model channel allows; no privileged record appears,
because privileged records are removed before scoring. The policy file is an
example configuration over fictional records, not the product's policy.

```console
$ stonewall packet "Where was the original binder kept, and did it ever leave?" --channel model --limit 4 --format text
packet  328d682da7d0  channel model  limit 4  view 5566e6cfcc01
S1  T0002:12-15@c85b86f76176  public
S2  T0002:19-21@c85b86f76176  public
S3  T0002:10-10@c85b86f76176  public
S4  D0002:12-13@d6c5ff4ce7df  confidential
```

**3a. A fluent, wrong answer.** It reads well and cites as if it were careful.

```console
$ cat examples/answers/fabricated.md
---
question: Where was the original binder kept, and did it ever leave?
channel: model
limit: 4
packet: 328d682da7d0db68924fba36384eae28dab36e7798c8cf285972fd71e7cee8a1
expect: not_retrieved quote_wrong_source quote_wrong_speaker uncited_claim unknown_artifact unknown_handle unsupported_figure unsupported_quote
---

The original binder never left the records room. The witness testified that
"the original never left the records room" [S1]. The witness signed it out on
March 13 [S1]. The witness also testified that "I compared all 42 pages" [S1].
The custodian kept "a sealed duplicate in the safe" [S2]. A standing order
required daily custody logs [Z0042:3-4]. Counsel proposed two deposition dates
[D0001:12-13]. The earlier summary confirms the same timeline [S9].
```

**3b. Its audit.** Every sentence fails for a different reason.

```console
$ stonewall audit-answer examples/answers/fabricated.md
answer   examples/answers/fabricated.md
packet   328d682da7d0  rebuilt 328d682da7d0  channel model
verdict  NOT GROUNDED  releasable to model
claim 1  9:1  uncited_claim
claim 2  9:50  quote_wrong_speaker  said by EXAMINING COUNSEL
claim 3  10:50  unsupported_figure
claim 4  11:16  quote_wrong_source  found in S2
claim 5  12:1  unsupported_quote
claim 6  12:59  unknown_artifact  Z0042:3-4
claim 7  13:42  not_retrieved  D0001:12-13
claim 8  14:16  unknown_handle  S9
[exit 1]
```

| Claim | Finding | What actually went wrong |
| --- | --- | --- |
| 1 | `uncited_claim` | A sentence with no source. |
| 2 | `quote_wrong_speaker` | Counsel's leading question presented as testimony. |
| 3 | `unsupported_figure` | A date the record does not contain. |
| 4 | `quote_wrong_source` | A real quote pinned to the wrong passage. |
| 5 | `unsupported_quote` | Words no record contains. |
| 6 | `unknown_artifact` | An authority that does not exist. |
| 7 | `not_retrieved` | A real document nobody retrieved. |
| 8 | `unknown_handle` | Evidence the model was never given. |

**4. A grounded answer.** The same question, answered from the packet. The
report says what was proven for each sentence: which handle backs it, how many
quotations matched verbatim, how many figures were found, and who said the
quoted words.

```console
$ stonewall audit-answer examples/answers/grounded.md
answer   examples/answers/grounded.md
packet   328d682da7d0  rebuilt 328d682da7d0  channel model
verdict  GROUNDED  releasable to model
claim 1  8:1  ok  statement  S1
claim 2  9:32  ok  quotation  S1  1 verbatim  said by THE WITNESS
claim 3  10:39  ok  figure  S1  2 figures
claim 4  11:30  ok  quotation  S2  1 verbatim  said by THE WITNESS
claim 5  12:42  ok  statement  S4
```

Change one word inside a quotation in `examples/answers/grounded.md` and rerun
step 4: that claim reports `unsupported_quote` and the command exits 1. Undo
the edit before continuing.

**5. Grounded is not the same as releasable.** Claim 5 rests on a confidential
preparation outline, so the same answer may not go to the `publish` channel.
The report names the handle and the designation, never the text. Release also
follows the declared packet: an answer written from a packet that held
confidential or privileged material cannot be released below that
designation, even if it cites only public handles.

```console
$ stonewall audit-answer examples/answers/grounded.md --release-to publish
answer   examples/answers/grounded.md
packet   328d682da7d0  rebuilt 328d682da7d0  channel model
verdict  GROUNDED  NOT RELEASABLE to publish
claim 1  8:1  ok  statement  S1
claim 2  9:32  ok  quotation  S1  1 verbatim  said by THE WITNESS
claim 3  10:39  ok  figure  S1  2 figures
claim 4  11:30  ok  quotation  S2  1 verbatim  said by THE WITNESS
claim 5  12:42  designation_exceeds_channel  S4  confidential exceeds publish
[exit 1]
```

**6. Internal reading.** On the `review` channel the privileged memo ranks S2
and S4. The model packet in step 2 is byte-identical whether this memo exists,
is deleted, or is rewritten to repeat every word of the question:
`test_model_packet_is_independent_of_privileged_records` and
`test_privileged_record_cannot_reorder_model_packet` in
`tests/test_grounding.py` prove it.

```console
$ stonewall packet "Where was the original binder kept, and did it ever leave?" --channel review --limit 4 --format text
packet  ee2b17de302f  channel review  limit 4  view b646d98abe2e
S1  T0002:12-15@c85b86f76176  public
S2  P0001:12-13@221e9e2a306b  privileged
S3  T0002:19-21@c85b86f76176  public
S4  P0001:17-17@221e9e2a306b  privileged
```

**7. The seeded defects.** Each row is a defect the named check must reject,
for the named rule or, for `unit` rows, the named test.

```console
$ stonewall checks --list
answers      answer-quote-drift               unsupported_quote
answers      answer-figure-drift              unsupported_figure
answers      answer-invented-authority        unknown_artifact
answers      answer-bracketed-quote           unsupported_quote
answers      answer-speaker-swap              quote_wrong_speaker
answers      answer-speaker-present-tense     quote_wrong_speaker
answers      answer-malformed-citation        malformed_citation
answers      answer-unbalanced-quotation      unbalanced_quotation
answers      answer-heading-fact              uncited_claim
answers      answer-link-target-text          unsupported_figure
answers      answer-speaker-lead-in           quote_wrong_speaker
answers      answer-month-swap                unsupported_figure
answers      answer-html-entity-quote         unsupported_markup
answers      answer-restricted-prose          designation_exceeds_channel
answers      answer-parenthetical-authority   malformed_citation
answers      record-edited-under-answer       packet_mismatch
answers      fabricated-answer-repaired       expectation_unmet
boundary     boundary-unapproved-path         unapproved_path
boundary     boundary-email-shape             email_address
boundary     boundary-byte-drift              manifest_drift
bundle       set-ordered-index                bundle_not_reproducible
corpus       record-duplicate-id              duplicate_artifact_id
disclosure   policy-ceiling-raised            fixed_decision_violated
disclosure   designation-case-variant         unknown_designation
speakers     transcript-unregistered-speaker  unregistered_speaker
speakers     registry-ambiguous-alias         ambiguous_alias
transcripts  readme-output-drift              transcript_drift
transcripts  readme-privileged-text           transcript_unpublishable
transcripts  transcript-privileged-heading    transcript_unpublishable
transcripts  transcript-reads-ignored-file    transcript_unsupported
unit         filter-after-scoring             test_privileged_record_cannot_reorder_model_packet
unit         span-digest-unchecked            test_citation_rejects_tampered_span_digest
unit         quote-check-disabled             test_fabricated_fixture_findings_are_pinned
unit         fixed-decision-removed           test_loosened_policy_is_refused
```

**8. Prove every check can fail.** This one runs live rather than as a
transcript, because it runs everything above against every seeded defect:

```bash
stonewall checks
```

Every check passes on an unmodified copy and writes nothing, and every seeded
defect is rejected for its named rule or test. The defects include filtering
after scoring, a set-ordered index that only cross-seed builds catch, a
disabled quote check, a swapped speaker, an edited record under an answer, and
drifted README output. Measured with `time` on the machine that generated these
transcripts, `stonewall checks` finished in under 6 seconds and steps 1 to 8
together in under 8 seconds.

## What each finding means

| Rule | The failure it prevents |
| --- | --- |
| `uncited_claim` | A statement of fact with no source behind it. |
| `malformed_citation` | A citation that cannot be read, so it supports nothing. |
| `unknown_handle` | A citation to evidence that was never provided. |
| `unknown_artifact` | A citation to a record that does not exist, or that this channel may not see. |
| `not_retrieved` | A citation to a real record that was not retrieved for this question. |
| `unbalanced_quotation` | A quotation that opens and never closes. |
| `unsupported_quote` | Quoted words that no cited record contains. |
| `quote_wrong_source` | Real words attributed to the wrong passage. |
| `quote_wrong_speaker` | Real words attributed to the wrong person, such as a question presented as an answer. |
| `unsupported_figure` | A number the cited lines do not contain, including a date whose month differs. |
| `packet_mismatch` | The record changed after the answer was written against it. |
| `empty_answer` | An answer with nothing in it to check. |
| `designation_exceeds_channel` | An answer that rests on, or repeats, material its destination may not receive. |
| `unsupported_markup` | Markup the audit does not read, which could hide words or a quotation from it. |

## Contracts

| Contract | Guarantee | Proof |
| --- | --- | --- |
| Content-addressed evidence | Canonical JSON, SHA-256 digests and a Merkle root bind every derived file to its sources, byte for byte across hash seeds. | `tests/test_evidence_fabric.py` |
| Line-verifiable citations | Every retrieval citation (`stonewall cite`, the evidence packet) carries a path, a line range, and artifact and span digests that are re-checked against the record on disk. | `tests/test_evidence_fabric.py` |
| Explainable BM25 retrieval | Every result exposes its BM25, exact-phrase and heading contributions. | `tests/test_evidence_fabric.py` |
| Fail-closed publication boundary | A path allowlist, content checks and an exact-tree manifest reject unreviewed files and byte drift. | `tests/test_publication_boundary.py` |
| Grounded answers | Every sentence must cite, and every bracketed citation, quotation and figure must resolve to the evidence packet the answer declares; a handle, address or artifact ID written outside brackets is malformed. | `tests/test_grounding.py` |
| Speaker-bound quotations | A quotation attributed to a speaker must lie inside one turn by that speaker. | `tests/test_attribution.py` |
| Designation flow control | Records above a channel's ceiling are removed before scoring, and an answer is releasable only where its declared packet and every cited source may go. | `tests/test_disclosure.py` |
| Checks that can fail | Every check passes on an unmodified copy, writes nothing, and rejects seeded defects for a named reason. | `tests/test_checks.py`, `tests/test_transcripts.py` |

## Every check can fail

The `checks --list` transcript above is the full registry. Each check runs on
a staged copy of exactly the publishable tree. A check that changes any file
in that copy fails. Each seeded defect is applied to a fresh copy and must be
rejected for its named rule or, for `unit` rows, its named test. Seeded
defects in the source of retrieval, packet construction, quote checking and
the fixed policy decisions are each caught by a named test. The bundle is
rebuilt under two hash seeds and compared byte for byte.

## Limits, stated plainly

- The audit proves provenance, not that a paraphrase is a fair reading of its
  source.
- A sentence ends at a terminal mark followed by whitespace; text run together
  after a period stays one sentence. There is no abbreviation list, so
  `Sept. 5` ends a sentence after `Sept.` and the part before it is reported
  as `uncited_claim`. A mark inside an ordinary bracket also ends a sentence,
  so `[sic.]` splits one; only citation brackets and quotations hold a
  sentence open. After a closing quotation mark the sentence continues unless
  a capital letter, a citation bracket or the paragraph end follows.
- Headings are audited as claims, so an uncited heading fails.
- An answer may use plain paragraphs, `-`/`*`/numbered list items at the start
  of a line, ATX headings, `>` block quotes, standalone thematic breaks
  (`---`), inline emphasis (`*`, `_`, `~`), inline code spans (audited as
  ordinary text), citation brackets, and `#anchor` link targets directly
  after a citation bracket. HTML, character references, backslash escapes,
  footnotes, invisible format characters, words mixing Latin with Cyrillic or
  Greek letters, images, other links, reference-style links and their
  definitions, `+` bullets, nested lists and lazy block-quote lines are
  refused as `unsupported_markup`. A list item's number is not audited.
- Answer front matter takes no `#` comment lines, so the question is the only
  free text it can carry.
- Items in a citation bracket are separated by `,` or `;`. A handle, address
  or artifact ID written outside a citation bracket is malformed.
- Quotations are compared after collapsing whitespace only. Ellipses are
  allowed; bracketed alterations are not. From a transcript, a quotation must
  lie within one turn, so a transcript heading cannot be quoted; an ellipsis
  cannot join two turns. An ellipsis may join in-order fragments of one turn;
  an elided quotation proves those words appear in that order, not what they
  mean together.
- Only double quotation marks (straight, curly, guillemets, fullwidth), single
  curly quotation marks and block quotes mark a quotation. The ASCII single
  quote is treated as an apostrophe, so words inside it are audited as an
  ordinary statement.
- A quotation is speaker-checked when a speech verb comes before it in the
  same sentence (or in a lead-in ending with a colon, for a block quote). The
  speech verbs are those in `attribution.ATTRIBUTION_VERBS`, for example said,
  stated, testified, answered and asked; any other verb is not read. The
  speaker is the registered alias directly before the last such verb:
  `Counsel for the witness said` binds THE WITNESS. If no registered alias is
  there and the quoted words come from a transcript, the quotation fails as
  `speaker not identified`. A quotation with no speech verb before it is not
  speaker-checked.
- A speaker is named by a registered alias read as written. A qualifier before
  it is not read (`opposing counsel` is read as `counsel`), and a possessive
  before it (`the defendant's counsel`) leaves the speaker unidentified.
- A figure is a number, optionally signed, with an optional month name before
  or after it and an optional scale word after it. Currency symbols are not
  compared. Units written as separate words are not compared; letters attached
  to a number (`42kg`, `650K`) are part of the figure, and so is an attached
  `%` or `‰`. Which event a figure belongs to is not compared, so two dates
  swapped within the cited lines still pass. A month is read when written
  directly before or after its day, or as `5th of April`, `the 3rd day of
  April` or `April the 3rd`; other phrasings (`April, 3`, `3 in April`) are
  not.
- A number glued to letters before it (`B13`, `April5`) is not a figure, and a
  range such as `3-5` is one figure. Superscript and fullwidth digits read as
  ordinary digits, and a no-break space as a space.
- Spelled-out numbers are not figures.
- Answers cite without pins; the declared packet digest binds them to the
  record instead.
- Confidential-text detection in transcripts compares whole lines of 20 or
  more characters, so partial-line excerpts are not detected.
- Answer prose and the `question:` line are screened for whole lines of 20 or
  more characters copied from records above the release channel, after
  normalizing case, dashes, emphasis, quotation marks and citation brackets
  (emphasis and code markers inside a word are deleted, as Markdown renders
  the word whole); shorter or partial excerpts are not detected.
- No model is called. The answers are fixtures standing in for model output.
- Designations here are synthetic labels on fictional records.

## Run everything

Python 3.12 or later and a git clone are required (`stonewall checks` and the
boundary check list files through Git, so they do not run from an archive
download). These are the commands CI runs:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p "test_*.py"
PYTHONPATH=src PYTHONHASHSEED=1 python3 -m stonewall build --output build/reference
PYTHONPATH=src PYTHONHASHSEED=2 python3 -m stonewall verify --output build/reference
PYTHONPATH=src python3 -m stonewall audit-answer examples/answers/grounded.md
PYTHONPATH=src python3 -m stonewall transcripts --check README.md
PYTHONPATH=src python3 scripts/check_public_boundary.py
PYTHONPATH=src python3 -m stonewall checks
```

`verify` rebuilds the bundle in a temporary directory and requires
byte-for-byte parity with the bundle on disk.

## Design rules

- Fail closed: an unknown designation, channel, transcript speaker label or
  command is refused, never skipped.
- Deterministic bytes: canonical JSON and stable ordering, independent of the
  hash seed.
- Findings carry locations, rule ids and handles, never quoted words, figures
  or source text.
- Standard library only.
- Every check ships with a seeded defect it must reject.

## Repository map

```text
.
├── build/                       # generated by `stonewall build`; ignored by git
├── examples/
│   ├── corpus/                  # synthetic coded records with designations
│   ├── answers/                 # a grounded answer and a fabricated one
│   ├── disclosure-policy.toml   # designations and channel ceilings
│   ├── speakers.toml            # transcript speaker labels and aliases
│   └── seeded-defects.toml      # defects each check must reject
├── scripts/
│   └── check_public_boundary.py # publication boundary command
├── src/stonewall/               # compiler, retrieval, packets, audit, checks
├── tests/                       # contract tests
├── AGENTS.md                    # contributor rules and commands
├── public-boundary.toml         # publication rules
├── public-tree-manifest.json    # exact reviewed tree
└── pyproject.toml               # package metadata and entry point
```

## Publication boundary

The publication check enumerates tracked and non-ignored files directly from
Git. It reports only rule identifiers and locations, never matched values.

## License

Source-available for evaluation, not open source. Downloading, cloning, or
running this repository means accepting its [LICENSE](LICENSE), which allows
evaluation for your own or your organization's internal, non-production use.
GitHub's terms let anyone view and fork it on GitHub. Production use,
modification, any other redistribution, training or evaluating a
machine-learning model with the software or its contents, adding them to a
dataset, and building a competing product require a separate signed
agreement with Stonewall Legal Enterprises, Inc. [LICENSE](LICENSE) governs.
