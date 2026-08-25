"""Line-addressed chunking and tokenization for explainable retrieval."""

from __future__ import annotations

import re
from collections.abc import Iterable

from .hashing import sha256_bytes
from .models import ArtifactRecord, ChunkRecord

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)?", re.IGNORECASE)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_SPACE_RE = re.compile(r"\s+")


def tokenize(value: str) -> tuple[str, ...]:
    """Return normalized retrieval terms while preserving repetitions."""
    return tuple(match.group(0).casefold() for match in _TOKEN_RE.finditer(value))


def normalize_excerpt(value: str, *, limit: int = 320) -> str:
    """Collapse display whitespace without changing the cited source bytes."""
    collapsed = _SPACE_RE.sub(" ", value).strip()
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def _nonempty_ranges(lines: tuple[str, ...]) -> Iterable[tuple[int, int]]:
    start: int | None = None
    for index, line in enumerate(lines):
        if line.strip() and start is None:
            start = index
        if not line.strip() and start is not None:
            yield start, index - 1
            start = None
    if start is not None:
        yield start, len(lines) - 1


def markdown_headings(lines: tuple[str, ...]) -> Iterable[tuple[int, int, str]]:
    """Yield headings outside fenced code blocks as index, level, and title."""
    fence_character: str | None = None
    fence_length = 0
    for index, line in enumerate(lines):
        fence_match = _FENCE_RE.match(line)
        if fence_character is not None:
            stripped = line.lstrip(" ")
            if (
                len(line) - len(stripped) <= 3
                and stripped.startswith(fence_character * fence_length)
                and not stripped.rstrip().strip(fence_character)
            ):
                fence_character = None
                fence_length = 0
            continue
        if fence_match:
            marker = fence_match.group(1)
            fence_character = marker[0]
            fence_length = len(marker)
            continue
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            yield index, len(heading_match.group(1)), heading_match.group(2).strip()


def chunk_artifact(artifact: ArtifactRecord) -> list[ChunkRecord]:
    """Split an artifact into deterministic heading-aware evidence spans."""
    body_lines = tuple(artifact.body.splitlines())
    if not body_lines:
        return []
    heading = artifact.title
    chunks: list[ChunkRecord] = []
    section_start = 0

    def emit(start: int, end: int, active_heading: str) -> None:
        if start > end:
            return
        section_lines = body_lines[start : end + 1]
        for paragraph_start, paragraph_end in _nonempty_ranges(section_lines):
            absolute_start = start + paragraph_start
            absolute_end = start + paragraph_end
            text = "\n".join(body_lines[absolute_start : absolute_end + 1])
            terms = tokenize(f"{active_heading}\n{text}")
            if not terms:
                continue
            line_start = artifact.body_start_line + absolute_start
            line_end = artifact.body_start_line + absolute_end
            identity = (
                f"{artifact.artifact_id}\0{line_start}\0{line_end}\0{text}"
            ).encode("utf-8")
            chunks.append(
                ChunkRecord(
                    chunk_id=f"CH-{sha256_bytes(identity)[:16]}",
                    artifact_id=artifact.artifact_id,
                    path=artifact.path,
                    artifact_sha256=artifact.sha256,
                    heading=active_heading,
                    line_start=line_start,
                    line_end=line_end,
                    text=text,
                    terms=terms,
                )
            )

    for index, _level, title in markdown_headings(body_lines):
        if index > section_start:
            emit(section_start, index - 1, heading)
        heading = title
        section_start = index
    emit(section_start, len(body_lines) - 1, heading)
    return chunks
