# Stonewall

**Citation-first legal document intelligence for litigation teams.**

Stonewall turns a structured litigation corpus into evidence that can be found,
explained, cited, and verified. This repository pairs the product story with a
compact, executable engineering reference built entirely on the Python standard
library.

[![Stonewall Home](https://img.shields.io/badge/Home-stnwl.ai-c96b3c?style=for-the-badge)](https://www.stnwl.ai/)
[![Organization](https://img.shields.io/badge/GitHub-stnwlai-111827?style=for-the-badge&logo=github)](https://github.com/stnwlai)
[![Verify](https://github.com/stnwlai/stnwl.ai/actions/workflows/verify.yml/badge.svg)](https://github.com/stnwlai/stnwl.ai/actions/workflows/verify.yml)
[![Python](https://img.shields.io/badge/Python-3.12-3776ab?style=flat-square)](#quickstart)
[![Node](https://img.shields.io/badge/Node.js-22-5fa04e?style=flat-square)](#verification)

## The product

Litigation teams do not need another document dump. They need a command surface
that answers practical questions:

- What evidence supports this assertion?
- Where did the quoted span come from?
- Why did this result rank above the next one?
- Has the underlying artifact changed since it was cited?

Stonewall makes those answers inspectable. The corpus remains readable on disk;
the derived catalog, search index, and citations remain reproducible from
the same sources.

## Engineering reference

The checked-in implementation concentrates on four contracts that reinforce one
another:

| Contract | What is demonstrable in this repository |
| --- | --- |
| **Content-addressed evidence** | Canonical JSON, artifact digests, a deterministic Merkle root, and a build attestation bind every generated surface to its inputs. |
| **Line-verifiable citations** | Each retrieval result carries an artifact ID, relative path, line range, artifact digest, and cited-span digest that can be checked against the source. |
| **Explainable retrieval** | Dependency-free BM25 ranking exposes its score components and adds deterministic heading and exact-phrase signals. |
| **Publication boundary** | An exact-tree manifest, metadata allowlist, path rules, and non-echoing content checks fail closed before publication. |

Read the concise design note in
[`docs/evidence-fabric.md`](docs/evidence-fabric.md), or start with the package in
[`src/stonewall/`](src/stonewall/).

## Quickstart

No service, database, model key, or third-party Python package is required.

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
```

The build emits three deterministic files:

```text
build/reference/
├── attestation.json
├── catalog.json
└── search-index.json
```

`verify` recompiles the corpus in an independent temporary build and requires byte-for-byte parity with
the bundle on disk. A changed artifact, citation span, catalog entry, or index
chunk therefore has an explicit verification consequence.

## Reference corpus

The generator-built corpus exercises the implementation across 78 artifacts:

| Surface | Count |
| --- | ---: |
| Matter records | 12 |
| Role cards | 10 |
| Pattern definitions | 8 |
| Total artifact classes | 8 |
| Line-addressed chunks | 554 |
| Deterministic bundle outputs | 3 |

Every record uses coded identifiers and the same three-field metadata contract.
The generator can prove that the checked-in corpus matches its deterministic
output:

```bash
python3 scripts/generate_sample_corpus.py --check
```

## Citation shape

A query result contains both an inspectable score and a verifiable citation:

```json
{
  "score_breakdown": {
    "bm25": 4.36619916,
    "exact_phrase": 0.0,
    "heading_boost": 0.95257955
  },
  "citation": {
    "address": "D0001:7-7@af7d25ba403d",
    "artifact_id": "D0001",
    "path": "depositions/D0001_outline.md",
    "line_start": 7,
    "line_end": 7
  }
}
```

The complete result also carries full SHA-256 digests for the artifact and
selected span. `--verify-citations` reopens the source, checks the artifact
digest, reselects the exact line range, and checks the span digest.

## Architecture

```text
Coded Markdown corpus
        |
        v
strict compiler + heading-aware chunker
                  |
                  v
explainable retrieval + verified citations
                  |
                  v
       content-addressed bundle
                  |
                  v
      reproducibility + boundary gates
```

This is intentionally a small, legible system: strict inputs, deterministic
derivations, source-addressed outputs, and failure modes that are easy to test.

## Publication boundary

[`public-boundary.toml`](public-boundary.toml) declares the repository boundary.
The checker enumerates tracked and non-ignored candidates directly from Git,
rejects denied paths and file types, validates the coded-corpus metadata
contract, scans common contact and credential shapes without printing matched
values, and compares every candidate with
[`public-tree-manifest.json`](public-tree-manifest.json).

```bash
PYTHONPATH=src python3 scripts/check_public_boundary.py
```

The committed manifest records each file's path, byte length, SHA-256 digest,
executable bit, content class, generator, and destination. Adding or changing a candidate without
refreshing and reviewing that manifest blocks CI.

## Verification

The pull-request gate runs:

```bash
node --test tests/tracker_helpers.test.mjs tests/email_consolidator.test.mjs
python3 -m unittest discover -s tests -p "test_*.py"
python3 scripts/generate_sample_corpus.py --check
PYTHONPATH=src python3 -m stonewall --corpus hoss-stonewall/sample_corpus build --output build/reference
PYTHONPATH=src python3 -m stonewall --corpus hoss-stonewall/sample_corpus verify --output build/reference
PYTHONPATH=src python3 scripts/check_public_boundary.py
python3 scripts/check_showcase_voice.py
python3 scripts/verify_repo_consistency.py
python3 scripts/repo_sweep.py
```

Tests cover strict parsing, coded-record provenance, byte-identical independent
builds, citation drift, retrieval explanations, boundary canaries,
manifest drift, and generator parity.

## Repository map

```text
.
├── src/stonewall/                # evidence compiler, retrieval, bundle, boundary
├── hoss-stonewall/sample_corpus/ # deterministic coded reference corpus
├── tests/                        # focused contracts plus existing automation tests
├── scripts/                      # corpus generator, boundary check, automation utilities
├── docs/                         # product site, portal, and engineering notes
├── public-boundary.toml          # declared publication rules
└── public-tree-manifest.json     # exact candidate-tree attestation
```

## Product surfaces

- [Stonewall home](https://www.stnwl.ai/)
- [Engineering showcase](https://stnwlai.github.io/stnwl.ai/)
- [Operator portal](https://stnwlai.github.io/stnwl.ai/portal/)
- [Official brief](docs/overview/official-brief.md)

## Security posture

- Credentials and environment-specific identifiers stay outside the repository.
- Generated evidence bundles are derived outputs and remain ignored by Git.
- Citation verification fails on source or span drift.
- Publication checks emit rule and location only, never the matched value.
- CI requires the candidate tree to match the reviewed publication manifest.

Stonewall turns document collections into an evidence surface that can explain
what it found and prove where it came from.
