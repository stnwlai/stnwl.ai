"""Immutable contracts shared by compilation, retrieval, and the local API."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    artifact_id: str
    artifact_type: str
    path: PurePosixPath
    sha256: str
    title: str
    body: str
    body_start_line: int
    total_lines: int
    event_date: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_manifest_entry(self) -> dict[str, Any]:
        return {
            "id": self.artifact_id,
            "type": self.artifact_type,
            "path": self.path.as_posix(),
            "sha256": self.sha256,
            "title": self.title,
            "event_date": self.event_date,
            "body_start_line": self.body_start_line,
            "total_lines": self.total_lines,
        }


@dataclass(frozen=True, slots=True)
class ChunkRecord:
    chunk_id: str
    artifact_id: str
    path: PurePosixPath
    artifact_sha256: str
    heading: str
    line_start: int
    line_end: int
    text: str
    terms: tuple[str, ...]

    def to_index_entry(self) -> dict[str, Any]:
        return {
            "id": self.chunk_id,
            "artifact_id": self.artifact_id,
            "path": self.path.as_posix(),
            "artifact_sha256": self.artifact_sha256,
            "heading": self.heading,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "text": self.text,
            "terms": list(self.terms),
            "length": len(self.terms),
        }


@dataclass(frozen=True, slots=True)
class Citation:
    artifact_id: str
    path: PurePosixPath
    line_start: int
    line_end: int
    artifact_sha256: str
    span_sha256: str

    @property
    def address(self) -> str:
        return (
            f"{self.artifact_id}:{self.line_start}-{self.line_end}"
            f"@{self.artifact_sha256[:12]}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "artifact_id": self.artifact_id,
            "path": self.path.as_posix(),
            "line_start": self.line_start,
            "line_end": self.line_end,
            "artifact_sha256": self.artifact_sha256,
            "span_sha256": self.span_sha256,
        }


@dataclass(frozen=True, slots=True)
class EvidenceHit:
    citation: Citation
    heading: str
    excerpt: str
    score: float
    score_breakdown: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation": self.citation.to_dict(),
            "heading": self.heading,
            "excerpt": self.excerpt,
            "score": round(self.score, 8),
            "score_breakdown": {
                key: round(value, 8)
                for key, value in sorted(self.score_breakdown.items())
            },
        }
