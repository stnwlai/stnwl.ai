"""Strict compiler from Markdown evidence records to immutable artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath

from .errors import CorpusValidationError
from .frontmatter import FrontMatterValue, ParsedDocument, parse_document
from .hashing import sha256_bytes
from .models import ArtifactRecord, ChunkRecord
from .text import chunk_artifact, markdown_headings

_ID_RE = re.compile(r"^[A-Z][A-Z0-9_-]*[0-9]{4}$")
_TYPE_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


@dataclass(frozen=True, slots=True)
class CompiledCorpus:
    root: Path
    artifacts: tuple[ArtifactRecord, ...]
    chunks: tuple[ChunkRecord, ...]

    @property
    def by_id(self) -> dict[str, ArtifactRecord]:
        return {artifact.artifact_id: artifact for artifact in self.artifacts}


def _scalar_string(
    metadata: dict[str, FrontMatterValue],
    key: str,
    *,
    source: str,
    required: bool = False,
) -> str | None:
    value = metadata.get(key)
    if value is None:
        if required:
            raise CorpusValidationError(f"{source}: missing required field {key!r}")
        return None
    if not isinstance(value, str):
        raise CorpusValidationError(f"{source}: field {key!r} must be a string")
    value = value.strip()
    if not value:
        raise CorpusValidationError(f"{source}: field {key!r} cannot be empty")
    return value


def _relative_source_path(root: Path, path: Path) -> PurePosixPath:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise CorpusValidationError(f"source escapes corpus root: {path}") from exc
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise CorpusValidationError(f"source path is not canonical: {relative}")
    return PurePosixPath(relative.as_posix())


def _source_uses_symlink(root: Path, path: Path) -> bool:
    """Return whether any corpus-relative path component is a symlink."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _artifact_from_document(
    root: Path,
    path: Path,
    raw: bytes,
    parsed: ParsedDocument,
) -> ArtifactRecord:
    relative = _relative_source_path(root, path)
    source = relative.as_posix()
    artifact_id = _scalar_string(parsed.metadata, "id", source=source, required=True)
    artifact_type = _scalar_string(
        parsed.metadata, "type", source=source, required=True
    )
    assert artifact_id is not None and artifact_type is not None
    if not _ID_RE.fullmatch(artifact_id):
        raise CorpusValidationError(f"{source}: invalid artifact id {artifact_id!r}")
    if not _TYPE_RE.fullmatch(artifact_type):
        raise CorpusValidationError(f"{source}: invalid artifact type {artifact_type!r}")
    title_matches = tuple(
        title
        for _index, level, title in markdown_headings(tuple(parsed.body.splitlines()))
        if level == 1
    )
    if len(title_matches) != 1:
        raise CorpusValidationError(f"{source}: artifact requires exactly one H1 title")
    event_date = _scalar_string(
        parsed.metadata, "date", source=source, required=True
    )
    assert event_date is not None
    if not _DATE_RE.fullmatch(event_date):
        raise CorpusValidationError(f"{source}: date must use YYYY-MM-DD")
    try:
        date.fromisoformat(event_date)
    except ValueError as exc:
        raise CorpusValidationError(f"{source}: date is not a calendar date") from exc
    return ArtifactRecord(
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        path=relative,
        sha256=sha256_bytes(raw),
        title=title_matches[0],
        body=parsed.body,
        body_start_line=parsed.body_start_line,
        total_lines=len(parsed.lines),
        event_date=event_date,
        metadata=dict(parsed.metadata),
    )


def compile_corpus(root: Path) -> CompiledCorpus:
    """Compile a corpus tree and fail closed on any structural drift."""
    root = root.resolve()
    if not root.is_dir():
        raise CorpusValidationError(f"corpus root does not exist: {root}")
    paths: list[Path] = []
    for path in sorted(root.rglob("*.md")):
        if path.name.casefold() == "readme.md":
            continue
        if _source_uses_symlink(root, path):
            raise CorpusValidationError("corpus sources cannot use symlinks")
        if not path.is_file():
            raise CorpusValidationError("corpus Markdown sources must be regular files")
        paths.append(path)
    if not paths:
        raise CorpusValidationError(f"corpus has no Markdown artifacts: {root}")
    artifacts: list[ArtifactRecord] = []
    seen_ids: dict[str, PurePosixPath] = {}
    for path in paths:
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CorpusValidationError(f"{path}: source is not UTF-8") from exc
        parsed = parse_document(text, source=path.relative_to(root).as_posix())
        artifact = _artifact_from_document(root, path, raw, parsed)
        if artifact.artifact_id in seen_ids:
            raise CorpusValidationError(
                f"duplicate artifact id {artifact.artifact_id}: "
                f"{seen_ids[artifact.artifact_id]} and {artifact.path}"
            )
        seen_ids[artifact.artifact_id] = artifact.path
        artifacts.append(artifact)
    ordered = tuple(sorted(artifacts, key=lambda item: (item.artifact_id, item.path)))
    chunks = tuple(
        chunk
        for artifact in ordered
        for chunk in chunk_artifact(artifact)
    )
    if len({chunk.chunk_id for chunk in chunks}) != len(chunks):
        raise CorpusValidationError("content-addressed chunk identity collision")
    return CompiledCorpus(root=root, artifacts=ordered, chunks=chunks)
