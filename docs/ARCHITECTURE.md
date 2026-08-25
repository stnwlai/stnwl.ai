# Architecture — Stonewall Evidence Reference

## System overview

The reference converts strict coded Markdown records into an evidence bundle
that can be rebuilt, queried, cited, and verified without an external runtime
dependency.

```text
┌──────────────────────────────────────────────────────────────┐
│ CODED CORPUS                                                 │
│ strict front matter · durable IDs · canonical dates          │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ COMPILER                                                     │
│ schema checks · artifact SHA-256 · heading-aware chunks      │
│ original line addresses                                      │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ RETRIEVAL                                                    │
│ BM25 · heading signal · phrase signal · cited source spans   │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ REPRODUCIBLE BUNDLE                                          │
│ catalog.json · search-index.json · attestation.json          │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ VERIFICATION                                                 │
│ byte parity · citation parity · exact publication tree       │
└──────────────────────────────────────────────────────────────┘
```

## Compiler contract

The compiler reads Markdown files and accepts a deliberately narrow front-matter
grammar. It fails on duplicate keys, malformed values, duplicate artifact IDs,
missing dates, and noncanonical line endings.

Accepted records become value objects with:

- a repository-relative path;
- a canonical artifact type, ID, and date;
- source lines and heading-aware chunks; and
- SHA-256 digests for artifact and chunk content.

## Retrieval and citation contract

Retrieval uses deterministic tokenization and BM25 scoring. A heading signal and
an exact-phrase signal remain separate in the result so ranking is inspectable.

Each hit contains a citation with the artifact path, original line range,
artifact digest, and selected-span digest. Verification checks the full artifact
before reselecting and hashing the cited lines.

## Bundle contract

The builder emits canonical JSON with stable key order and newline handling. Its
attestation records the corpus Merkle root and the digest of each generated
surface. A verifier rebuilds the expected bytes in memory and compares every
output.

The output directory is owned narrowly: unknown files cause the build to fail,
and an output path inside the source corpus is rejected.

## Publication contract

The publication checker derives its candidate set from Git, including tracked
and non-ignored files. It applies denied-path and file-type rules, a three-field
coded metadata schema, and non-echoing checks for common contact and credential
shapes. Finally, it requires the candidate tree to match a manifest containing
each file's path, size, digest, executable bit, content class, generator, and destination.

## Commands

```bash
PYTHONPATH=src python3 -m stonewall \
  --corpus hoss-stonewall/sample_corpus \
  build --output build/reference

PYTHONPATH=src python3 -m stonewall \
  --corpus hoss-stonewall/sample_corpus \
  query "deposition scheduling" --limit 3 --verify-citations

PYTHONPATH=src python3 -m stonewall \
  --corpus hoss-stonewall/sample_corpus \
  verify --output build/reference

PYTHONPATH=src python3 scripts/check_public_boundary.py
```
