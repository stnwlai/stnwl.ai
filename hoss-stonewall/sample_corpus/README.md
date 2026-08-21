# Showcase Corpus

This directory holds 78 working artifacts across eight categories that
exercise the Stonewall ingest, manifest, classification, and verification
surfaces end-to-end:

| Directory       | Count | What it represents                                            |
|-----------------|-------|---------------------------------------------------------------|
| `cases/`        | 12    | Matter postures, key dates, pattern tags                      |
| `depositions/`  | 10    | Witness outlines                                              |
| `transcripts/`  | 8     | Status-conference transcripts                                 |
| `emails/`       | 14    | Counsel-to-counsel correspondence                             |
| `motions/`      | 10    | Motion-to-compel filings                                      |
| `characters/`   | 10    | Cast cards (adjuster, expert, witness, defense counsel)       |
| `patterns/`     | 8     | Phenomenology pattern definitions                             |
| `billing/`      | 6     | Period billing statements                                     |

## Verification

Every artifact is exercised by **9 checks** in
[`tests/test_sample_corpus.py`](../../tests/test_sample_corpus.py):

1. `exists`
2. `non_empty`
3. `is_utf8`
4. `has_yaml_front_matter`
5. `front_matter_has_id`
6. `front_matter_has_type`
7. `has_h1_heading`
8. `ends_with_newline`
9. `body_has_content`

That produces **702 per-artifact tests + 5 corpus-wide invariants =
707 tests** in this module alone, contributing to the showcase's 700+
test verification suite.

## Regenerating

The corpus is deterministic. To regenerate after editing the generator:

```bash
python3 scripts/generate_sample_corpus.py
```
