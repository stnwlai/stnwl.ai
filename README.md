# Stonewall Evidence Reference

[![Verify](https://github.com/stnwlai/stnwl.ai/actions/workflows/verify.yml/badge.svg)](https://github.com/stnwlai/stnwl.ai/actions/workflows/verify.yml)

A runnable reference for checking citations, quotations and disclosure rules
against fictional legal records. Standard-library Python; no model calls or
network access.

[stnwl.ai](https://stnwl.ai) is Stonewall's public site. This repository contains
the public reference; the Stonewall application and working corpus are
maintained separately.

## Try it

Use Python 3.12 or later and a Git clone. From the repository root:

```bash
alias stonewall='PYTHONPATH=src python3 -m stonewall'
```

Read a cited passage. The command checks its digest before printing it:

```console
$ stonewall cite T0002:12-15
T0002:12-15@c85b86f76176  transcripts/T0002_custody.md  public
  12  EXAMINING COUNSEL: Where was the original binder kept during March?
  13  THE WITNESS: In the records room. I kept a working copy at my desk.
  14  EXAMINING COUNSEL: So the original never left the records room?
  15  THE WITNESS: It left once. I signed it out on March 3 and returned it on March 5.
```

Retrieve evidence for a question. The example `model` channel permits public
and confidential records; privileged records are excluded before scoring.
The returned handles are the answer's allowed sources.

```console
$ stonewall packet "Where was the original binder kept, and did it ever leave?" --channel model --limit 4 --format text
packet  328d682da7d0  channel model  limit 4  view 5566e6cfcc01
S1  T0002:12-15@c85b86f76176  public
S2  T0002:19-21@c85b86f76176  public
S3  T0002:10-10@c85b86f76176  public
S4  D0002:12-13@d6c5ff4ce7df  confidential
```

Audit the [fabricated answer](examples/answers/fabricated.md). The report
identifies missing citations, invented evidence, incorrect figures and words
attributed to the wrong speaker:

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

The [grounded answer](examples/answers/grounded.md) passes that audit. It still
cannot be published: its packet includes confidential evidence. Release rules
apply to the whole packet, even when an answer cites only public sources.

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

Console blocks are generated from these commands and checked by CI.
Designations and channel rules are examples, not legal privilege decisions.

## What the reference checks

| Check | Implementation and tests |
| --- | --- |
| Reproducible evidence bundles, line citations and BM25 retrieval scores | [Evidence tests](tests/test_evidence_fabric.py) |
| Citations, quotations and figures resolve to the declared evidence packet | [Answer audit](src/stonewall/grounding.py), [tests](tests/test_grounding.py) |
| Attributed quotations belong to the named speaker's turn | [Speaker tests](tests/test_attribution.py) |
| Retrieval and release respect the example channel policy | [Disclosure tests](tests/test_disclosure.py) |
| Published files match the reviewed tree and content rules | [Publication tests](tests/test_publication_boundary.py) |
| Checks reject seeded defects and README output matches the commands | [Check tests](tests/test_checks.py), [transcript tests](tests/test_transcripts.py) |

## Limits

The audit checks sources, not whether an answer is a fair or legally sound
reading of them. A passing result does not establish that a paraphrase is
supported or that a number describes the right event.

- Sentence splitting and Markdown support are deliberately limited. Headings
  are claims; abbreviations can split sentences; unsupported markup fails.
- Quotations match after whitespace normalization, with ellipses allowed.
  ASCII single quotes do not mark quotations. Speaker attribution recognizes
  only registered aliases and a fixed list of speech verbs.
- Figure checks do not interpret spelled-out numbers, currency symbols,
  separate unit words or the event a number describes.
- Restricted-text screening detects whole source lines at or above its length
  threshold. It can miss shorter or partial excerpts and paraphrases.
- Answers are fixtures. The reference does not generate them or determine
  whether a real document is privileged.

The full parsing and matching rules are documented in
[grounding.py](src/stonewall/grounding.py) and
[attribution.py](src/stonewall/attribution.py). Transcript screening is in
[transcripts.py](src/stonewall/transcripts.py).

## Run the checks

These are the CI commands. Build output is ignored by Git; verification
rebuilds it under a different hash seed and compares the bytes.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p "test_*.py"
PYTHONPATH=src PYTHONHASHSEED=1 python3 -m stonewall build --output build/reference
PYTHONPATH=src PYTHONHASHSEED=2 python3 -m stonewall verify --output build/reference
PYTHONPATH=src python3 -m stonewall audit-answer examples/answers/grounded.md
PYTHONPATH=src python3 -m stonewall transcripts --check README.md
PYTHONPATH=src python3 scripts/check_public_boundary.py
PYTHONPATH=src python3 -m stonewall checks
```

`stonewall checks` runs each check on an unchanged copy, then on copies with
[seeded defects](examples/seeded-defects.toml). Each defect must fail for its
named rule or test. Checks must leave their input files unchanged.

The fictional records, answer fixtures and example policies are in
[examples/](examples/). See [AGENTS.md](AGENTS.md) for contribution rules and
the required transcript and manifest refresh steps.

## License

Source-available for internal, non-production evaluation. [LICENSE](LICENSE)
governs use and distribution.
