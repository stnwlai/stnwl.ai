"""Line-addressed chunking, tokenization, and verbatim matching for evidence."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from .hashing import sha256_bytes
from .models import ArtifactRecord, ChunkRecord

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)?", re.IGNORECASE)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_SPACE_RE = re.compile(r"\s+")
_ELLIPSIS_RE = re.compile(r"\.\.\.|…")
_DIGIT_CONTINUES_RE = re.compile(r"[.,:/-]\d")
_DIGIT_PRECEDES_RE = re.compile(r"\d[.,:/-]")
MONTHS: tuple[str, ...] = (
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December",
)
_MONTH_NAMES = {month[:3].casefold(): month for month in MONTHS}
_MONTH = "(?i:(?:" + "|".join((*MONTHS, "Sept", *(m[:3] for m in MONTHS))) + r")\.?)"
_START = r"(?<![0-9A-Za-z])(?<!\d[.,:/-])"
FIGURE_RE = re.compile(
    _START + r"(?P<day>\d{1,2})(?i:st|nd|rd|th)?\s+(?:(?i:of)\s+)?(?P<dmonth>" + _MONTH
    + r")(?![0-9A-Za-z])"
    r"|(?:(?<![0-9A-Za-z])(?P<month>" + _MONTH + r")\s+)?"
    + _START + r"(?P<number>(?:[-+\u2212](?=\d))?\d+(?:[.,:/-]\d+)*[A-Za-z]*[%\u2030]?)"
    r"(?:\s+(?P<scale>(?i:thousand|million|billion|trillion))(?![0-9A-Za-z]))?"
)
_FIGURE_SPACE_RE = re.compile(r"[*_~]")
_ORDINAL_RE = re.compile(r"(.*\d)(?i:st|nd|rd|th)")


def tokenize(value: str) -> tuple[str, ...]:
    """Return normalized retrieval terms while preserving repetitions."""
    return tuple(match.group(0).casefold() for match in _TOKEN_RE.finditer(value))


def normalize_excerpt(value: str, *, limit: int = 320) -> str:
    """Collapse display whitespace without changing the cited source bytes."""
    collapsed = _SPACE_RE.sub(" ", value).strip()
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def collapse_whitespace(value: str) -> str:
    """Collapse every whitespace run to one space; line wraps are layout."""
    return _SPACE_RE.sub(" ", value).strip()


def _bounded(fragment: str, text: str, start: int) -> bool:
    """Whether *fragment* at *start* neither splits a word nor truncates a number."""
    end = start + len(fragment)
    if fragment[0].isalnum() and start and text[start - 1].isalnum():
        return False
    if fragment[-1].isalnum() and end < len(text) and text[end].isalnum():
        return False
    if fragment[-1].isdecimal() and _DIGIT_CONTINUES_RE.match(text, end):
        return False
    preceding = text[max(start - 2, 0) : start]
    return not (fragment[0].isdecimal() and _DIGIT_PRECEDES_RE.fullmatch(preceding))


def quotation_in(quotation: str, text: str) -> bool:
    """Whether *quotation* appears verbatim in *text*, modulo whitespace runs.

    Case, punctuation, and Unicode forms are significant. An ellipsis splits the
    quotation into fragments that must appear in order. Fragment edges sit on
    word boundaries and never cut a number short.
    """
    haystack = collapse_whitespace(text)
    pieces = _ELLIPSIS_RE.split(collapse_whitespace(quotation))
    fragments = [piece.strip() for piece in pieces if piece.strip()]
    if not fragments:
        return False
    position = 0
    for fragment in fragments:
        start = haystack.find(fragment, position)
        while start != -1 and not _bounded(fragment, haystack, start):
            start = haystack.find(fragment, start + 1)
        if start == -1:
            return False
        position = start + len(fragment)
    return True


def _figure_key(match: re.Match[str]) -> tuple[str, str, str]:
    """Month, signed number, and scale of one figure match, normalized."""
    if match.group("day"):
        return _MONTH_NAMES[match.group("dmonth")[:3].casefold()], match.group("day"), ""
    month = _MONTH_NAMES.get((match.group("month") or "")[:3].casefold(), "")
    number = match.group("number").replace("\u2212", "-")
    ordinal = _ORDINAL_RE.fullmatch(number)
    scale = (match.group("scale") or "").lower()
    return month, ordinal.group(1) if ordinal else number, scale


def _figure_text(text: str) -> str:
    """*text* NFKC-folded, so superscript and fullwidth digits read as digits and
    non-breaking spaces as spaces, with emphasis markers read as spaces."""
    return collapse_whitespace(_FIGURE_SPACE_RE.sub(" ", unicodedata.normalize("NFKC", text)))


def figure_tokens(text: str) -> tuple[str, ...]:
    """Normalized figures in *text*: '<Month> <number> <scale>', unused parts omitted."""
    return tuple(
        " ".join(part for part in _figure_key(match) if part)
        for match in FIGURE_RE.finditer(_figure_text(text))
    )


def figure_in(figure: str, text: str) -> bool:
    """Whether the figure token *figure* appears in *text*.

    Numbers compare as whole signed tokens with any ordinal suffix dropped, and
    a day before its month reads as the month before its day. A figure without
    a month or scale matches the same number under any qualifiers; a qualified
    figure needs the same month and scale too.
    """
    wanted = [_figure_key(match) for match in FIGURE_RE.finditer(figure)]
    if len(wanted) != 1:
        return False
    month, number, scale = wanted[0]
    for match in FIGURE_RE.finditer(_figure_text(text)):
        found_month, found_number, found_scale = _figure_key(match)
        if found_number == number and (
            not (month or scale) or (found_month, found_scale) == (month, scale)
        ):
            return True
    return False


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
            heading_match = _HEADING_RE.fullmatch(text)
            is_heading_chunk = (
                heading_match is not None
                and heading_match.group(2).strip() == active_heading
            )
            terms = tokenize(text if is_heading_chunk else f"{active_heading}\n{text}")
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
                    designation=artifact.designation,
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
