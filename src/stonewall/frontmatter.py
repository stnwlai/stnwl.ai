"""Strict, dependency-free front-matter parsing for reference artifacts.

The three-field corpus contract needs only nonempty strings. Matching single or
double quotes are accepted and removed; every other YAML feature is out of
scope.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import FrontMatterError

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_NON_LF_LINE_SEPARATORS = ("\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029")


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    metadata: dict[str, str]
    body: str
    body_start_line: int
    lines: tuple[str, ...]


def _parse_value(value: str, *, source: str, line_number: int) -> str:
    value = value.strip()
    if not value:
        raise FrontMatterError(f"{source}:{line_number}: value cannot be empty")
    quote_characters = {"'", '"'}
    if value[0] in quote_characters or value[-1] in quote_characters:
        if len(value) < 2 or value[0] != value[-1]:
            raise FrontMatterError(f"{source}:{line_number}: malformed quoted value")
        value = value[1:-1]
        if not value:
            raise FrontMatterError(f"{source}:{line_number}: value cannot be empty")
    return value


def parse_document(text: str, *, source: str = "<memory>") -> ParsedDocument:
    """Parse a Markdown artifact and retain its original line-addressing."""
    if any(separator in text for separator in _NON_LF_LINE_SEPARATORS):
        raise FrontMatterError(f"{source}: only LF line separators are canonical")
    lines = tuple(text.splitlines())
    if not lines or lines[0] != "---":
        raise FrontMatterError(f"{source}: front matter must start on line 1")
    try:
        closing_index = lines.index("---", 1)
    except ValueError as exc:
        raise FrontMatterError(f"{source}: front matter is not terminated") from exc
    metadata: dict[str, str] = {}
    for index, line in enumerate(lines[1:closing_index], start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise FrontMatterError(f"{source}:{index}: expected 'key: value'")
        key, raw_value = line.split(":", 1)
        key = key.strip()
        if not _KEY_RE.fullmatch(key):
            raise FrontMatterError(f"{source}:{index}: invalid key {key!r}")
        if key in metadata:
            raise FrontMatterError(f"{source}:{index}: duplicate key {key!r}")
        metadata[key] = _parse_value(raw_value, source=source, line_number=index)
    body_lines = lines[closing_index + 1 :]
    while body_lines and not body_lines[0]:
        body_lines = body_lines[1:]
        closing_index += 1
    body = "\n".join(body_lines)
    if text.endswith("\n") and body:
        body += "\n"
    return ParsedDocument(
        metadata=metadata,
        body=body,
        body_start_line=closing_index + 2,
        lines=lines,
    )
