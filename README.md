# Stonewall

[![Verify](https://github.com/stnwlai/stnwl.ai/actions/workflows/verify.yml/badge.svg)](https://github.com/stnwlai/stnwl.ai/actions/workflows/verify.yml)

Stonewall helps legal teams find, read, and reason from the record.

This is Stonewall's public marketing repository. It includes a runnable
example of evidence retrieval and answer auditing using synthetic legal
records. The product and real corpus are maintained in
[stnwlai/stonewall](https://github.com/stnwlai/stonewall).

[Website](https://stnwl.ai) · [Example records](examples/corpus) · [Source](src/stonewall)

## Try the demo

Requires Python 3.12 or later and Git. No third-party Python packages,
credentials, or services are needed to run the demo.

```bash
git clone https://github.com/stnwlai/stnwl.ai.git
cd stnwl.ai
alias stonewall='PYTHONPATH=src python3 -m stonewall'
```

Audit the [deliberately incorrect answer](examples/answers/fabricated.md):

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

The failure is expected. Compare it with the [grounded answer](examples/answers/grounded.md)
and inspect its source:

```bash
stonewall audit-answer examples/answers/grounded.md
stonewall cite T0002:12-15
```

The grounded answer passes its evidence audit. Adding `--release-to publish`
rejects release because its packet includes confidential example material.
Release rules apply to the whole packet, even if an answer cites only public
sources. All designations and records in this demo are fictional.

## What the example checks

- Citations resolve to retrieved evidence and verified source lines.
- Quotations, figures, and registered speaker attributions match their sources.
- Record designations restrict retrieval and answer release.
- Content hashes and reproducible builds detect changes to evidence.
- Publication checks reject unreviewed files, and seeded defects test the checks.

The audit checks provenance. It does not establish legal correctness, decide
whether a paraphrase fairly represents its source, or determine which event a
number describes. Text parsing uses a limited Markdown grammar.
Restricted-text screening can miss shorter excerpts, partial lines, and
paraphrases. The detailed rules live with the
[audit implementation](src/stonewall/grounding.py).

The demo runs locally and makes no model calls. CI checks the generated
console output above against the command.

## Development

Run the unit tests and the checks against seeded defects:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p "test_*.py"
PYTHONPATH=src python3 -m stonewall checks
```

See [AGENTS.md](AGENTS.md) for contributor rules, all CI commands, and the
steps for refreshing generated transcripts and the publication manifest.

## License

Source-available for internal, non-production evaluation under [LICENSE](LICENSE).
Modification, production use, redistribution, and model training or evaluation
require a separate agreement. GitHub viewing and forking rights are unaffected.
