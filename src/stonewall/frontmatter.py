"""Strict, dependency-free front-matter parsing for reference artifacts.

The compiler intentionally supports a small data language: scalar values and
single-line lists. A narrow grammar is easier to validate, diff, and reproduce
than an environment-dependent YAML implementation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TypeAlias

from .errors import FrontMatterError

Scalar: TypeAlias = str | int | float | bool
FrontMatterValue: TypeAlias = Scalar | list[Scalar]

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_INTEGER_RE = re.compile(r"^-?(?:0|[1-9][0-9]*)$")
_FLOAT_RE = re.compile(r"^-?(?:0|[1-9][0-9]*)\.[0-9]+$")
_NON_LF_LINE_SEPARATORS = ("\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029")


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    metadata: dict[str, FrontMatterValue]
    body: str
    body_start_line: int
    lines: tuple[str, ...]


def _split_list(value: str, *, source: str, line_number: int) -> list[str]:
    inner = value[1:-1].strip()
    if not inner:
        return []
    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for character in inner:
        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
            current.append(character)
            continue
        if character == "," and quote is None:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(character)
    if quote is not None:
        raise FrontMatterError(
            f"{source}:{line_number}: unterminated quote in list value"
        )
    parts.append("".join(current).strip())
    if any(not part for part in parts):
        raise FrontMatterError(f"{source}:{line_number}: empty list item")
    return parts


def _parse_scalar(value: str, *, source: str, line_number: int) -> Scalar:
    value = value.strip()
    if not value:
        raise FrontMatterError(f"{source}:{line_number}: value cannot be empty")
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if _INTEGER_RE.fullmatch(value):
        return int(value)
    if _FLOAT_RE.fullmatch(value):
        return float(value)
    return value


def _parse_value(value: str, *, source: str, line_number: int) -> FrontMatterValue:
    stripped = value.strip()
    if stripped.startswith("[") or stripped.endswith("]"):
        if not (stripped.startswith("[") and stripped.endswith("]")):
            raise FrontMatterError(f"{source}:{line_number}: malformed list value")
        return [
            _parse_scalar(part, source=source, line_number=line_number)
            for part in _split_list(stripped, source=source, line_number=line_number)
        ]
    return _parse_scalar(stripped, source=source, line_number=line_number)


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
    metadata: dict[str, FrontMatterValue] = {}
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
