# Stonewall Evidence Reference

An executable reference for source-addressed legal evidence.

[![Verify](https://github.com/stnwlai/stnwl.ai/actions/workflows/verify.yml/badge.svg)](https://github.com/stnwlai/stnwl.ai/actions/workflows/verify.yml)

This repository is intentionally narrow. It demonstrates four contracts and
nothing else:

| Contract | Proof in this repository |
| --- | --- |
| Content-addressed evidence | Canonical JSON, SHA-256 artifact digests, a deterministic Merkle root, and a build attestation bind derived files to their sources. |
| Line-verifiable citations | Results carry a source path, line range, artifact digest, and cited-span digest that can be checked against the Markdown record. |
| Explainable BM25 retrieval | Every result exposes BM25, exact-phrase, and heading contributions to its score. |
| Fail-closed publication boundary | A path allowlist, content checks, metadata rules, and an exact-tree manifest reject unreviewed files or byte drift. |

The implementation uses the Python standard library. The six coded Markdown
records under `examples/corpus/` are sufficient to exercise compilation,
retrieval, citation verification, and reproducible builds without describing a
hosted system, integrations, or operational architecture.

## Run and verify

Python 3.12 or later is required.

```bash
PYTHONPATH=src python3 -m stonewall build --output build/reference

PYTHONPATH=src python3 -m stonewall \
  query "deposition dates" --limit 1 --verify-citations

PYTHONPATH=src python3 -m stonewall verify --output build/reference

PYTHONPATH=src python3 scripts/check_public_boundary.py
```

`build` writes three deterministic files:

```text
build/reference/
├── attestation.json
├── catalog.json
└── search-index.json
```

`verify` rebuilds the bundle independently in a temporary directory and
requires byte-for-byte parity with the bundle on disk.

## Citation shape

Each hit includes an inspectable score and a source-bound citation:

```json
{
  "score_breakdown": {
    "bm25": 2.63722661,
    "exact_phrase": 0.0,
    "heading_boost": 0.67546843
  },
  "citation": {
    "address": "D0001:7-7@378413c01a54",
    "artifact_id": "D0001",
    "path": "depositions/D0001_scheduling.md",
    "line_start": 7,
    "line_end": 7,
    "artifact_sha256": "378413c01a54defad4b74d3be9e791436e695fdcae9db71fa52752418c5ff65c",
    "span_sha256": "ad243452a9fb35e1730d40b63c3b7d218d76095926b70c17a4fe3827f6762028"
  }
}
```

With `--verify-citations`, the reader reopens the source, verifies the artifact
digest, reselects the stated lines, and verifies the selected span.

## Repository map

```text
.
├── examples/corpus/             # six coded source records
├── src/stonewall/               # compiler, retrieval, bundle, boundary
├── tests/                        # contract tests
├── public-boundary.toml          # publication rules
└── public-tree-manifest.json     # exact reviewed tree
```

## Publication boundary

The publication check enumerates tracked and non-ignored files directly from
Git. It reports only rule identifiers and locations, never matched values.
