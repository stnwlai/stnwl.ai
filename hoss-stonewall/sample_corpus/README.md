# Coded Reference Corpus

This directory holds 78 working artifacts across eight categories. Coded matter
identifiers exercise the Stonewall compiler, retrieval, citation, and
verification contracts end to end.

| Directory       | Count | What it represents                                            |
|-----------------|-------|---------------------------------------------------------------|
| `cases/`        | 12    | Coded matter postures, key dates, pattern tags                |
| `depositions/`  | 10    | Role-addressed deposition plans                               |
| `transcripts/`  | 8     | Status-conference transcripts                                 |
| `emails/`       | 14    | Counsel-to-counsel correspondence                             |
| `motions/`      | 10    | Motion-to-compel filings                                      |
| `characters/`   | 10    | Coded role cards                                               |
| `patterns/`     | 8     | Neutral procedure-signal definitions                          |
| `billing/`      | 6     | Period billing statements                                     |

## Verification

The corpus is checked at three levels:

1. Per-file shape checks require UTF-8, strict front matter, headings, and body
   content.
2. The evidence compiler rejects duplicate IDs, malformed dates, and structural
   drift.
3. Reproducibility tests require independent bundles to be byte-identical and
   every returned citation to verify against its source lines.

## Regenerating

The corpus is deterministic. To regenerate after editing the generator:

```bash
python3 scripts/generate_sample_corpus.py
```

To compare the checked-in tree with a fresh generation without changing files:

```bash
python3 scripts/generate_sample_corpus.py --check
```
