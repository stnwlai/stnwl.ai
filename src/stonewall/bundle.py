"""Reproducible public bundles with a content-addressed attestation."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from . import __version__
from .compiler import CompiledCorpus, compile_corpus
from .errors import CorpusValidationError
from .hashing import canonical_json_bytes, merkle_root, sha256_bytes

BUNDLE_FILES = ("catalog.json", "search-index.json", "attestation.json")


def _payloads(corpus: CompiledCorpus) -> dict[str, dict[str, Any]]:
    corpus_root_hash = merkle_root(
        (artifact.path.as_posix(), artifact.sha256) for artifact in corpus.artifacts
    )
    catalog = {
        "schema_version": 1,
        "corpus_root": corpus_root_hash,
        "artifact_count": len(corpus.artifacts),
        "artifacts": [artifact.to_manifest_entry() for artifact in corpus.artifacts],
    }
    search_index = {
        "schema_version": 1,
        "corpus_root": corpus_root_hash,
        "chunk_count": len(corpus.chunks),
        "chunks": [chunk.to_index_entry() for chunk in corpus.chunks],
    }
    serialized = {
        "catalog.json": canonical_json_bytes(catalog),
        "search-index.json": canonical_json_bytes(search_index),
    }
    attestation = {
        "schema_version": 1,
        "builder": "stonewall-evidence",
        "builder_version": __version__,
        "corpus_root": corpus_root_hash,
        "artifact_count": len(corpus.artifacts),
        "chunk_count": len(corpus.chunks),
        "outputs": {
            name: sha256_bytes(value) for name, value in sorted(serialized.items())
        },
    }
    return {
        "catalog.json": catalog,
        "search-index.json": search_index,
        "attestation.json": attestation,
    }


def build_bundle(corpus_root: Path, output_dir: Path) -> dict[str, Any]:
    """Compile and publish the three-file reference bundle."""
    corpus = compile_corpus(corpus_root)
    payloads = _payloads(corpus)
    output_dir = output_dir.resolve()
    if output_dir == Path(output_dir.anchor):
        raise CorpusValidationError("output directory cannot be a filesystem root")
    try:
        output_dir.relative_to(corpus.root)
    except ValueError:
        pass
    else:
        raise CorpusValidationError("output directory cannot be inside the corpus")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stonewall-build-", dir=output_dir.parent) as raw:
        staging = Path(raw)
        for name, payload in payloads.items():
            (staging / name).write_bytes(canonical_json_bytes(payload))
        output_dir.mkdir(parents=True, exist_ok=True)
        for existing in output_dir.iterdir():
            if existing.name not in BUNDLE_FILES:
                raise CorpusValidationError(
                    f"refusing to replace unowned output path: {existing.name}"
                )
            if existing.is_symlink() or not existing.is_file():
                raise CorpusValidationError(
                    f"refusing to replace non-regular output path: {existing.name}"
                )
        for name in BUNDLE_FILES:
            os.replace(staging / name, output_dir / name)
    return payloads["attestation.json"]


def bundle_bytes(output_dir: Path) -> dict[str, bytes]:
    """Read a complete bundle and reject missing or unexpected files."""
    if not output_dir.is_dir():
        raise CorpusValidationError(f"bundle directory does not exist: {output_dir}")
    entries = tuple(output_dir.iterdir())
    names = {path.name for path in entries}
    expected = set(BUNDLE_FILES)
    if names != expected:
        raise CorpusValidationError(
            f"bundle file set differs: missing={sorted(expected - names)}, "
            f"unexpected={sorted(names - expected)}"
        )
    invalid = sorted(
        path.name for path in entries if path.is_symlink() or not path.is_file()
    )
    if invalid:
        raise CorpusValidationError(
            f"bundle contains non-regular outputs: {', '.join(invalid)}"
        )
    return {name: (output_dir / name).read_bytes() for name in BUNDLE_FILES}


def verify_bundle(corpus_root: Path, output_dir: Path) -> dict[str, Any]:
    """Rebuild independently and require byte-for-byte output parity."""
    actual = bundle_bytes(output_dir)
    with tempfile.TemporaryDirectory(prefix="stonewall-verify-") as raw:
        candidate_dir = Path(raw) / "bundle"
        build_bundle(corpus_root, candidate_dir)
        candidate = bundle_bytes(candidate_dir)
    differences = [name for name in BUNDLE_FILES if actual[name] != candidate[name]]
    if differences:
        raise CorpusValidationError(
            f"bundle is not reproducible; differing files: {', '.join(differences)}"
        )
    try:
        attestation = json.loads(actual["attestation.json"])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CorpusValidationError("attestation is not valid JSON") from exc
    for name, expected_digest in attestation.get("outputs", {}).items():
        if name not in actual or sha256_bytes(actual[name]) != expected_digest:
            raise CorpusValidationError(f"attestation digest mismatch: {name}")
    return attestation
