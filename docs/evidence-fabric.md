# Evidence Fabric

Stonewall's engineering reference turns a directory of coded Markdown records
into a reproducible evidence bundle. It focuses on four composable contracts:
deterministic compilation, verifiable citations, explainable retrieval, and an
exact publication boundary.

## 1. Deterministic compilation

The compiler accepts a deliberately narrow front-matter grammar and rejects
ambiguous inputs such as duplicate keys, invalid identifiers, missing dates, and
CRLF source text. Every accepted artifact receives a
SHA-256 digest before it is divided into heading-aware, line-addressed chunks.

The builder then emits canonical JSON for:

- an artifact catalog;
- a retrieval index; and
- an attestation binding those files to the corpus Merkle root.

Two independent builds from the same inputs must be byte-identical. Verification
rebuilds the expected bytes rather than trusting timestamps or cached state.

## 2. Verifiable citations

A citation is an addressable claim about source text. It includes:

- the artifact ID and repository-relative path;
- the original line range;
- the full artifact digest;
- the selected-span digest; and
- a compact display address such as `D0001:7-7@af7d25ba403d`.

Verification reopens the artifact, checks its digest, selects the stated lines,
and checks the span digest. Artifact edits and line-level citation drift therefore
fail explicitly.

## 3. Explainable retrieval

Retrieval uses dependency-free BM25 with deterministic tokenization. Every hit
reports the components that produced its rank:

- BM25 relevance;
- an exact-phrase signal; and
- a heading signal.

Results are returned with source excerpts and citations, so relevance and
provenance travel together.

## 4. Exact publication boundary

The publication checker derives its candidate set from Git's tracked and
non-ignored files. It then applies path and file-type rules, text checks that do
not echo matched values, and a strict metadata contract for the coded corpus.

The final manifest records a digest, size, executable bit, content class,
generator, and destination for each candidate. CI rejects both unreviewed additions and byte
drift in existing entries.

## Run the contracts

```bash
python3 scripts/generate_sample_corpus.py --check

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

The implementation lives in [`../src/stonewall/`](../src/stonewall/), with its
contract tests in [`../tests/test_evidence_fabric.py`](../tests/test_evidence_fabric.py)
and [`../tests/test_publication_boundary.py`](../tests/test_publication_boundary.py).
