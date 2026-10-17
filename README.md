# Stonewall

Find, read, and reason from the legal record.

**[Visit Stonewall](https://stnwl.ai)**

This is Stonewall's public marketing repository. The product and real corpus
live in [stnwlai/stonewall](https://github.com/stnwlai/stonewall).

## Evidence demo

The included demo uses fictional legal records to:

- Trace citations to retrieved evidence and exact source lines.
- Check quotations, numbers, and speaker attributions against their sources.
- Apply disclosure rules to retrieval and answer release.

The audit checks provenance. A passing result does not establish legal correctness.

[Explore the records](examples/corpus) · [Read the source](src/stonewall)

<details>
<summary>Run the evidence demo</summary>

Requires Python 3.12 or later and Git. The demo uses only the Python standard
library and runs locally, without credentials, services, or model calls.

```bash
git clone https://github.com/stnwlai/stnwl.ai.git
cd stnwl.ai
alias stonewall='PYTHONPATH=src python3 -m stonewall'
stonewall audit-answer examples/answers/grounded.md
stonewall cite T0002:12-15
```

The [grounded answer](examples/answers/grounded.md) passes its evidence audit.
The citation command prints the source passage after verifying its digest.
Compare that with the [deliberately incorrect answer](examples/answers/fabricated.md):

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

This failure is expected. CI checks the displayed output against the command.

To check whether the grounded answer can be published:

```bash
stonewall audit-answer examples/answers/grounded.md --release-to publish
```

This also exits with status 1: its packet includes confidential example
material. Release rules apply to the whole packet, even if an answer cites
only public sources. These designations are fictional, not legal privilege decisions.

**Audit limits.** The checks do not decide whether a paraphrase fairly represents
its source or which event a number describes. Text parsing uses a limited
Markdown grammar. Restricted-text screening can miss shorter excerpts, partial
lines, and paraphrases. See the [audit implementation](src/stonewall/grounding.py)
for the matching rules.

</details>

[Contributor guide](AGENTS.md) · [Verification](https://github.com/stnwlai/stnwl.ai/actions/workflows/verify.yml) · [Evaluation license](LICENSE)

Source-available for internal, non-production evaluation. Modification,
production use, redistribution, and model training or evaluation require a
separate agreement. GitHub viewing and forking rights are unaffected.
