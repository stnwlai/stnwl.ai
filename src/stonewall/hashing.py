"""Deterministic hashing primitives used by every generated surface."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def sha256_bytes(value: bytes) -> str:
    """Return the lowercase SHA-256 digest for *value*."""
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    """Hash a file without loading it into memory all at once."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON into the repository's byte-stable representation."""
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def merkle_root(leaves: Iterable[tuple[str, str]]) -> str:
    """Build a deterministic binary Merkle root from ``(path, digest)`` leaves.

    Leaf ordering is part of the contract. Odd levels duplicate the final node,
    which makes the result stable and independently reproducible.
    """
    nodes = [
        hashlib.sha256(f"leaf\0{path}\0{digest}".encode("utf-8")).digest()
        for path, digest in sorted(leaves)
    ]
    if not nodes:
        return sha256_bytes(b"")
    while len(nodes) > 1:
        if len(nodes) % 2:
            nodes.append(nodes[-1])
        nodes = [
            hashlib.sha256(b"node\0" + nodes[index] + nodes[index + 1]).digest()
            for index in range(0, len(nodes), 2)
        ]
    return nodes[0].hex()
