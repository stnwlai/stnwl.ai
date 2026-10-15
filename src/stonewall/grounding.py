"""Grounded answers: every sentence bound to the evidence packet it cites.

An answer declares the question, channel, limit, and digest of the evidence
packet it was written against. The audit rebuilds that packet and checks each
sentence against it. It proves provenance, not entailment.

NORMATIVE RULES

Front matter
- Parsed with frontmatter.parse_document. The keys are exactly channel, limit,
  packet and question, plus an optional expect; anything else is refused.
- limit is a decimal integer from 1 to 20; packet is 64 lowercase hex digits.
- expect is space-separated, sorted, unique, and a subset of RULES.

Claims
- Body paragraphs split at blank lines. A heading is a line of up to three
  spaces, one to six '#', then whitespace or the line end; any other line
  starting with '#' is text. A heading holding a digit or a quotation
  mark is audited as a claim of its own, without its '#' markers; other
  headings are structure. A leading '- ', '* ', '<n>. ' or '<n>) ' (n of one to
  three digits) starts a paragraph and is excluded.
- A paragraph whose every line starts with '>' is a block quote: one claim
  whose quotation is its lines with '>' and one optional space stripped, minus
  trailing citation brackets. Only refs inside it back it, and it has no
  speaker check.
- A sentence ends at '.', '?' or '!' outside quotations and outside brackets.
  After the mark, a run of '*', '_', ')', U+2019, "'" and footnote markers
  '[^...]' is skipped; whitespace or the end of the paragraph must follow. A
  closing quotation mark directly after one of those marks ends the sentence
  after the mark. A '.' between digits never ends a sentence. There is no
  abbreviation list.
- Citation brackets that follow the end, after whitespace, belong to the
  sentence that just ended.

Quotations
- The pairs are straight double quotes, U+201C/U+201D, guillemets, fullwidth
  double quotes, and U+2018/U+2019, where the closing U+2019 is the first one
  not followed by a letter. Quotations count only outside citation brackets,
  and brackets inside a quotation are quoted text.
- An opening mark not closed in its paragraph is unbalanced_quotation, and that
  segment is not checked. So is any other quotation punctuation (Unicode Pi or
  Pf, or U+FF02) outside a pair, except U+2019 between two letters.
- The ASCII single quote is never a quotation mark.

Citation brackets
- A closed bracket is citation-shaped when its content holds a handle or an
  address token, or starts with an uppercase letter, holds no bracket, and
  contains a digit. A following '(...)' link target is part of it and is not
  text. Other brackets ([sic], [emphasis added]) are ordinary text, and the
  quotations and figures inside them are checked.
- Items are separated by ',' with optional spaces. Each item is a handle S<n>,
  n from 1 to MAX_PACKET_LIMIT with no leading zero, or an address
  <ID>:<start>[-<end>] in the retrieval grammar, without a pin, with start <=
  end.
- Any other citation-shaped bracket, including one holding a nested bracket,
  is malformed_citation and counts as no ref. Its finding names only the
  position of the first bad item.

Resolution
- Refs resolve against the view of the declared channel, never the full
  corpus, so a record above that channel's ceiling behaves exactly like one
  that does not exist.
- A handle not in the packet is unknown_handle. An ID not in the view is
  unknown_artifact. An ID in the view whose range no packet entry covers is
  not_retrieved. A narrower range inside a returned span is backed.
- A handle contributes its whole entry text. A narrowed address contributes
  only its own lines of the covering entry.

Uncited
- A claim with no well-formed ref is uncited_claim, and its quotations,
  figures and speakers are not checked.

Quotation check, for each balanced quotation
- It is found in a span when text.quotation_in holds and, if the span has
  speaker turns, holds within one turn's text.
- Found in a contributed span: proven, then speaker-checked.
- Else, when a contributed span holds it only across turns: unsupported_quote,
  detail 'spans turns'.
- Else found in any packet entry's full text, including the same entry outside
  a narrowed range: quote_wrong_source, detail 'found in S<n>', the first such
  entry in rank order.
- Else unsupported_quote.

Speaker check
- The attribution is speakers.attribution_phrase over the claim text before
  the opening mark, with citation brackets and earlier quotations blanked so
  offsets hold. Without a speech-verb phrase ending that text there is no
  speaker check.
- Turns are computed over the full entry text; a narrowed address keeps the
  turns that intersect its range.
- With a bound mention, some span the quotation is found in must have one turn
  by the mention's label holding it; otherwise quote_wrong_speaker, detail
  'said by <LABEL>' from the first such span's single speaker, or 'no recorded
  speaker'.
- With no bound mention, quote_wrong_speaker, detail 'speaker not identified',
  when any span the quotation is found in has speaker turns.

Figure check
- Figures are text.FIGURE_RE tokens outside quotations, citation brackets and
  footnote markers: an optionally signed number with an optional month before
  it and scale word after it. Each must satisfy text.figure_in for at least one
  contributed span, else unsupported_figure. Spelled-out numbers are not
  figures.

Packet check
- The packet is rebuilt for the declared question, channel and limit. A digest
  differing from the declared one is packet_mismatch on the packet line.
  Claims are still audited against the rebuilt packet.

Release check
- release_to defaults to the declared channel; an unknown one raises
  DisclosureError unknown_channel.
- Every ref that resolved to a record in the view, backed or not_retrieved,
  whose designation is not releasable on release_to is
  designation_exceeds_channel, detail '<designation> exceeds <release_to>'.
- The answer is releasable when disclosure.decide allows, on release_to, the
  join of every packet entry's designation and every such cited designation.
  When that join exceeds release_to and no ref reported it, the answer gets
  designation_exceeds_channel at the packet line, detail 'packet
  <designation> exceeds <release_to>'.

Verdict
- Grounded means no finding other than designation_exceeds_channel; ok means
  grounded and releasable. No claims is empty_answer.

Findings sit at the line and column of the claim's first character, or claim 0
for answer-level findings. They carry rule ids, refs as written, handles,
designations, channels and speaker labels, never quoted words, figures or
source text.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .attribution import SpeakerRegistry, Turn, speaker_of, speaker_turns
from .compiler import CompiledCorpus
from .disclosure import Decision, DisclosurePolicy, channel_view, decide
from .errors import AnswerError, DisclosureError, FrontMatterError
from .frontmatter import parse_document
from .packet import MAX_PACKET_LIMIT, EvidencePacket, PacketEntry, build_packet
from .retrieval import ADDRESS_RE
from .text import figure_in, figure_tokens, quotation_in

RULES: tuple[str, ...] = (
    "uncited_claim", "malformed_citation", "unknown_handle", "unknown_artifact", "not_retrieved",
    "unbalanced_quotation", "unsupported_quote", "quote_wrong_source", "quote_wrong_speaker",
    "unsupported_figure", "packet_mismatch", "empty_answer", "designation_exceeds_channel",
)
ANSWER_FIELDS = frozenset({"channel", "limit", "packet", "question"})
OPTIONAL_FIELDS = frozenset({"expect"})
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_LIMIT_RE = re.compile(r"^[1-9][0-9]?$")
_HANDLE_RE = re.compile(r"^S([1-9][0-9]*)$")
_BRACKET_RE = re.compile(r"^[A-Z][^\[\]]*$")
_CITATION_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])(?:S\d+|[A-Z][A-Z0-9_-]*\d{4}:\d)")
_ITEM_SEPARATOR_RE = re.compile(r"\s*,\s*")
_HEADING_RE = re.compile(r" {0,3}#{1,6}(?:\s+|$)(?P<text>.*?)(?:\s+#+)?\s*$")
_ITEM_RE = re.compile(r"(?:[-*]|\d{1,3}[.)])\s")
_FOOTNOTE_RE = re.compile(r"\[\^[^\[\]\s]*\]")
_SENTENCE_MARKS = ".?!"
_AFTER_MARK = "*_)\u2019'"
_CLOSERS = {
    '"': '"', "\u201c": "\u201d", "\u00ab": "\u00bb", "\uff02": "\uff02", "\u2018": "\u2019",
}


@dataclass(frozen=True, slots=True)
class AnswerDocument:
    path: str
    question: str
    channel: str
    limit: int
    packet: str
    packet_line: int
    expect: tuple[str, ...] | None
    body: str
    body_start_line: int


@dataclass(frozen=True, slots=True)
class CitationRef:
    written: str
    offset: int
    handle: str | None
    artifact_id: str | None
    line_start: int | None
    line_end: int | None


@dataclass(frozen=True, slots=True)
class Quotation:
    text: str
    offset: int


@dataclass(frozen=True, slots=True)
class Claim:
    index: int
    offset: int
    text: str
    refs: tuple[CitationRef, ...]
    malformed: tuple[int, ...]  # 1-based first bad item of each malformed bracket
    quotations: tuple[Quotation, ...]
    figures: tuple[str, ...]
    unbalanced: int | None

    @property
    def kind(self) -> str:
        if self.quotations:
            return "quotation"
        return "figure" if self.figures else "statement"


@dataclass(frozen=True, slots=True, order=True)
class AuditFinding:
    line: int
    column: int
    claim: int
    rule: str
    ref: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "column": self.column,
            "detail": self.detail,
            "line": self.line,
            "ref": self.ref,
            "rule": self.rule,
        }


@dataclass(frozen=True, slots=True)
class ClaimProof:
    claim: int
    line: int
    column: int
    kind: str
    backed_by: tuple[str, ...]
    quotations: int
    figures: int
    speakers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "backed_by": list(self.backed_by),
            "claim": self.claim,
            "column": self.column,
            "figures": self.figures,
            "kind": self.kind,
            "line": self.line,
            "quotations": self.quotations,
            "speakers": list(self.speakers),
        }


@dataclass(frozen=True, slots=True)
class AnswerAudit:
    answer: str
    channel: str
    release_to: str
    declared_packet: str
    rebuilt_packet: str
    release: Decision
    claims: tuple[ClaimProof, ...]
    findings: tuple[AuditFinding, ...]

    @property
    def grounded(self) -> bool:
        return all(f.rule == "designation_exceeds_channel" for f in self.findings)

    @property
    def releasable(self) -> bool:
        return self.release.allowed

    @property
    def ok(self) -> bool:
        return self.grounded and self.releasable

    def rules(self) -> tuple[str, ...]:
        return tuple(sorted({finding.rule for finding in self.findings}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "channel": self.channel,
            "release_to": self.release_to,
            "grounded": self.grounded,
            "releasable": self.releasable,
            "packet": {
                "declared": self.declared_packet,
                "matches": self.declared_packet == self.rebuilt_packet,
                "rebuilt": self.rebuilt_packet,
            },
            "claims": [proof.to_dict() for proof in self.claims],
            "findings": [finding.to_dict() for finding in self.findings],
        }

    def render_text(self) -> str:
        packet = (
            f"{self.declared_packet[:12]}  rebuilt {self.rebuilt_packet[:12]}"
            f"  channel {self.channel}"
        )
        verdict = "GROUNDED" if self.grounded else "NOT GROUNDED"
        release = "releasable to" if self.releasable else "NOT RELEASABLE to"
        lines = [
            f"{'answer':<7}  {self.answer}",
            f"{'packet':<7}  {packet}",
            f"{'verdict':<7}  {verdict}  {release} {self.release_to}",
        ]
        for finding in self.findings:
            if not finding.claim:
                lines.append(_row("answer", finding))
        for proof in self.claims:
            label = f"claim {proof.claim}"
            rows = [_row(label, f) for f in self.findings if f.claim == proof.claim]
            lines.extend(rows or [_ok_row(proof)])
        return "\n".join(lines)


def _row(label: str, finding: AuditFinding) -> str:
    fields = (label, f"{finding.line}:{finding.column}", finding.rule, finding.ref, finding.detail)
    return "  ".join(field for field in fields if field)


def _ok_row(proof: ClaimProof) -> str:
    fields = (
        f"claim {proof.claim}",
        f"{proof.line}:{proof.column}",
        "ok",
        proof.kind,
        ",".join(proof.backed_by),
        f"{proof.quotations} verbatim" if proof.quotations else "",
        f"{proof.figures} figures" if proof.figures else "",
        f"said by {','.join(proof.speakers)}" if proof.speakers else "",
    )
    return "  ".join(field for field in fields if field)


def parse_answer(text: str, *, source: str) -> AnswerDocument:
    """Parse an answer document and refuse any noncanonical front matter."""
    try:
        parsed = parse_document(text, source=source)
    except FrontMatterError as exc:
        raise AnswerError(str(exc)) from exc
    metadata = parsed.metadata
    keys = set(metadata)
    if not ANSWER_FIELDS <= keys or keys - ANSWER_FIELDS - OPTIONAL_FIELDS:
        raise AnswerError(
            f"{source}: answer front matter takes exactly channel, limit, packet,"
            " question, and optionally expect"
        )
    if not _LIMIT_RE.fullmatch(metadata["limit"]) or int(metadata["limit"]) > MAX_PACKET_LIMIT:
        raise AnswerError(f"{source}: limit must be a decimal integer 1..{MAX_PACKET_LIMIT}")
    if not _DIGEST_RE.fullmatch(metadata["packet"]):
        raise AnswerError(f"{source}: packet must be a lowercase SHA-256 digest")
    expect: tuple[str, ...] | None = None
    if "expect" in metadata:
        items = metadata["expect"].split(" ")
        if items != sorted(set(items)) or not set(items) <= set(RULES):
            raise AnswerError(f"{source}: expect must be sorted, unique, known rule ids")
        expect = tuple(items)
    packet_line = next(
        number
        for number, line in enumerate(parsed.lines, start=1)
        if line.split(":", 1)[0].strip() == "packet"
    )
    return AnswerDocument(
        path=source,
        question=metadata["question"],
        channel=metadata["channel"],
        limit=int(metadata["limit"]),
        packet=metadata["packet"],
        packet_line=packet_line,
        expect=expect,
        body=parsed.body,
        body_start_line=parsed.body_start_line,
    )


def load_answer(path: Path, *, source: str) -> AnswerDocument:
    """Read and parse an answer file; unreadable or non-UTF-8 bytes are refused."""
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise AnswerError(f"{source}: answer is unreadable or not UTF-8") from exc
    return parse_answer(text, source=source)


@dataclass(frozen=True, slots=True)
class _Layout:
    """Brackets and quotations of one text as ``(start, end)`` spans."""

    citations: tuple[tuple[int, int], ...]  # citation-shaped, with any link target
    brackets: tuple[tuple[int, int], ...]  # every other closed bracket
    quotations: tuple[tuple[int, int], ...]
    opened: int | None  # an opening mark never closed
    stray: int | None  # the first quotation mark outside any recognized pair

    @property
    def unbalanced(self) -> int | None:
        marks = [mark for mark in (self.opened, self.stray) if mark is not None]
        return min(marks) if marks else None


def _quote_mark(text: str, index: int) -> bool:
    """Whether ``text[index]`` is quotation punctuation, not an in-word apostrophe."""
    character = text[index]
    if character in ('"', "\uff02"):
        return True
    if unicodedata.category(character) not in ("Pi", "Pf"):
        return False
    return not (
        character == "\u2019"
        and 0 < index < len(text) - 1
        and text[index - 1].isalpha()
        and text[index + 1].isalpha()
    )


def _closes(text: str, index: int, opener: str) -> bool:
    if text[index] != _CLOSERS[opener]:
        return False
    # A right single quotation mark followed by a letter is an apostrophe.
    return opener != "\u2018" or index + 1 == len(text) or not text[index + 1].isalpha()


def _matching(text: str, start: int) -> int | None:
    """Index of the ']' closing the '[' at *start*, counting nested brackets."""
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "[":
            depth += 1
        elif text[index] == "]":
            depth -= 1
            if not depth:
                return index
    return None


def _citation_shaped(content: str) -> bool:
    return _CITATION_TOKEN_RE.search(content) is not None or (
        _BRACKET_RE.fullmatch(content) is not None
        and any(character.isdigit() for character in content)
    )


def _layout(text: str) -> _Layout:
    citations: list[tuple[int, int]] = []
    brackets: list[tuple[int, int]] = []
    quotations: list[tuple[int, int]] = []
    opened: int | None = None
    stray: int | None = None
    index = 0
    while index < len(text):
        character = text[index]
        if opened is not None:
            if _closes(text, index, text[opened]):
                quotations.append((opened, index + 1))
                opened = None
        elif character == "[" and (close := _matching(text, index)) is not None:
            if _citation_shaped(text[index + 1 : close]):
                end = close + 1
                if text.startswith("(", end) and (target := text.find(")", end)) != -1:
                    end = target + 1  # a Markdown link target is not text
                citations.append((index, end))
                index = end
                continue
            brackets.append((index, close + 1))
        elif character in _CLOSERS:
            opened = index
        elif stray is None and _quote_mark(text, index):
            stray = index
        index += 1
    return _Layout(tuple(citations), tuple(brackets), tuple(quotations), opened, stray)


def _hidden_spans(text: str, layout: _Layout) -> list[tuple[int, int]]:
    """Citations, footnote markers, quotations, and an unclosed quotation's tail."""
    footnotes = [
        (low, high) for low, high in layout.brackets if _FOOTNOTE_RE.fullmatch(text, low, high)
    ]
    tail = [(layout.opened, len(text))] if layout.opened is not None else []
    return [*layout.citations, *footnotes, *layout.quotations, *tail]


def _masked(text: str) -> str:
    """*text* with every hidden span blanked to spaces, so offsets hold."""
    characters = list(text)
    for start, end in _hidden_spans(text, _layout(text)):
        characters[start:end] = " " * (end - start)
    return "".join(characters)


def _parse_items(content: str, offset: int) -> tuple[tuple[CitationRef, ...], int]:
    """Refs in one bracket, or ``((), k)`` for its first bad item k (1-based)."""
    refs: list[CitationRef] = []
    position = 0
    for number, item in enumerate(_ITEM_SEPARATOR_RE.split(content), start=1):
        position = content.find(item, position) if item else position
        at = offset + position
        position += len(item)
        handle = _HANDLE_RE.fullmatch(item)
        if handle is not None and int(handle.group(1)) <= MAX_PACKET_LIMIT:
            refs.append(CitationRef(item, at, item, None, None, None))
            continue
        match = ADDRESS_RE.fullmatch(item)
        if match is None or match.group("pin") is not None:
            return (), number
        start = int(match.group("start"))
        end = int(match.group("end") or start)
        if end < start:
            return (), number
        refs.append(CitationRef(item, at, None, match.group("id"), start, end))
    return tuple(refs), 0


def _audited_heading(text: str) -> bool:
    return any(c.isdigit() or _quote_mark(text, i) for i, c in enumerate(text))


def _paragraphs(body: str) -> list[tuple[int, int, bool]]:
    """Paragraph spans, flagged True for a heading audited as its own claim."""
    spans: list[tuple[int, int, bool]] = []
    start: int | None = None
    end = 0
    offset = 0
    for line in body.split("\n"):
        heading = _HEADING_RE.match(line)
        item = None if heading else _ITEM_RE.match(line)
        if not line.strip() or heading or item:
            if start is not None:
                spans.append((start, end, False))
            start = offset + item.end() if item else None
            if heading and _audited_heading(heading.group("text")):
                spans.append((offset + heading.start("text"), offset + heading.end("text"), True))
        elif start is None:
            start = offset
        end = offset + len(line)
        offset += len(line) + 1
    if start is not None:
        spans.append((start, end, False))
    return spans


def _sentences(text: str) -> list[tuple[int, int]]:
    """Sentence spans of one paragraph, each with its trailing citation brackets."""
    layout = _layout(text)
    hidden = [False] * len(text)
    for low, high in _hidden_spans(text, layout):
        hidden[low:high] = [True] * (high - low)
    bracketed = [False] * len(text)
    for low, high in (*layout.citations, *layout.brackets):
        bracketed[low:high] = [True] * (high - low)
    closing = {high - 1 for _low, high in layout.quotations}
    trailing = dict(layout.citations)

    def end_after(index: int) -> int | None:
        """Where the sentence ends if the mark at *index* ends it, else None."""
        if bracketed[index]:
            return None
        if index in closing:
            if text[index - 1] not in _SENTENCE_MARKS:
                return None
        elif hidden[index] or text[index] not in _SENTENCE_MARKS:
            return None
        end = index + 1
        while end < len(text):
            if text[end] in _AFTER_MARK:
                end += 1
            elif footnote := _FOOTNOTE_RE.match(text, end):
                end = footnote.end()
            else:
                break
        # Whitespace or the paragraph end must follow, so a '.' between digits
        # never ends a sentence.
        return end if end == len(text) or text[end].isspace() else None

    spans: list[tuple[int, int]] = []
    start: int | None = None
    for index in range(len(text)):
        if start is None:
            if index >= (spans[-1][1] if spans else 0) and not text[index].isspace():
                start = index
            continue
        if (mark_end := end_after(index)) is None:
            continue
        end = mark_end
        while (following := len(text) - len(text[end:].lstrip())) in trailing:
            end = trailing[following]
        if end > mark_end and end < len(text) and end not in closing:
            end = end_after(end) or end  # '"Quoted." [S1].' keeps its final mark
        spans.append((start, end))
        start = None
    if start is not None:
        spans.append((start, len(text.rstrip())))
    return spans


def _refs(text: str, layout: _Layout, base: int) -> tuple[list[CitationRef], list[int]]:
    refs: list[CitationRef] = []
    malformed: list[int] = []
    for low, high in layout.citations:
        close = _matching(text, low)
        found, bad = _parse_items(text[low + 1 : close], base + low + 1)
        refs.extend(found)
        if bad:
            malformed.append(bad)
    return refs, malformed


def _block_quotation(paragraph: str) -> str:
    """A block quote's text: '>' and one space stripped, minus trailing citations."""
    quoted = "\n".join(re.sub(r"^> ?", "", line) for line in paragraph.split("\n"))
    starts = {high: low for low, high in _layout(quoted).citations}
    end = len(quoted.rstrip())
    while True:
        if end in starts:
            end = len(quoted[: starts[end]].rstrip())
        elif end and quoted[end - 1] in _SENTENCE_MARKS and end - 1 in starts:
            end -= 1
        else:
            return quoted[:end]


def split_claims(body: str) -> tuple[Claim, ...]:
    """Split an answer body into claims with their refs, quotations and figures."""
    claims: list[Claim] = []
    for paragraph_start, paragraph_end, heading in _paragraphs(body):
        paragraph = body[paragraph_start:paragraph_end]
        if not heading and all(line.startswith(">") for line in paragraph.split("\n")):
            refs, malformed = _refs(paragraph, _layout(paragraph), paragraph_start)
            quoted = _block_quotation(paragraph)
            claims.append(
                Claim(
                    index=len(claims) + 1,
                    offset=paragraph_start,
                    text=paragraph,
                    refs=tuple(refs),
                    malformed=tuple(malformed),
                    quotations=(Quotation(quoted, paragraph_start),) if quoted.strip() else (),
                    figures=(),
                    unbalanced=None,
                )
            )
            continue
        for start, end in _sentences(paragraph):
            text = paragraph[start:end]
            layout = _layout(text)
            base = paragraph_start + start
            refs, malformed = _refs(text, layout, base)
            claims.append(
                Claim(
                    index=len(claims) + 1,
                    offset=base,
                    text=text,
                    refs=tuple(refs),
                    malformed=tuple(malformed),
                    quotations=tuple(
                        Quotation(text[open_ + 1 : close - 1], base + open_)
                        for open_, close in layout.quotations
                    ),
                    figures=figure_tokens(_masked(text)),
                    unbalanced=None if layout.unbalanced is None else base + layout.unbalanced,
                )
            )
    return tuple(claims)


@dataclass(frozen=True, slots=True)
class _Span:
    """The text one ref contributes, with the turns that ref may speak for."""

    handle: str
    text: str
    turns: tuple[Turn, ...]


def _entry_turns(entry: PacketEntry) -> tuple[Turn, ...]:
    return speaker_turns(entry.text, entry.hit.citation.line_start)


def _labels(quotation: str, turns: tuple[Turn, ...]) -> set[str]:
    """Labels of the turns that each contain *quotation* whole."""
    return {turn.label for turn in turns if quotation_in(quotation, turn.text)}


def _in_one_turn(quotation: str, turns: tuple[Turn, ...]) -> bool:
    """Whether a span with turns holds *quotation* inside one turn; no turns passes."""
    return not turns or bool(_labels(quotation, turns))


def _contribution(entry: PacketEntry, ref: CitationRef) -> _Span:
    first = entry.hit.citation.line_start
    turns = _entry_turns(entry)
    if ref.line_start is None or ref.line_end is None:
        return _Span(entry.handle, entry.text, turns)
    lines = entry.text.split("\n")[ref.line_start - first : ref.line_end - first + 1]
    return _Span(
        entry.handle,
        "\n".join(lines),
        tuple(t for t in turns if t.line_start <= ref.line_end and t.line_end >= ref.line_start),
    )


def _position(document: AnswerDocument, offset: int) -> tuple[int, int]:
    line = document.body_start_line + document.body.count("\n", 0, offset)
    return line, offset - document.body.rfind("\n", 0, offset)


def _audit_claim(
    claim: Claim,
    document: AnswerDocument,
    packet: EvidencePacket,
    view: CompiledCorpus,
    policy: DisclosurePolicy,
    speakers: SpeakerRegistry,
    release_to: str,
    cited: list[str],
) -> tuple[ClaimProof, list[AuditFinding]]:
    line, column = _position(document, claim.offset)
    findings: list[AuditFinding] = []

    def report(rule: str, ref: str = "", detail: str = "") -> None:
        findings.append(AuditFinding(line, column, claim.index, rule, ref, detail))

    for item in claim.malformed:
        report("malformed_citation", detail=f"item {item}")
    spans: list[_Span] = []
    for ref in claim.refs:
        if ref.handle is not None:
            entry = packet.entry(ref.handle)
            if entry is None:
                report("unknown_handle", ref.written)
                continue
            designation = entry.designation
            spans.append(_contribution(entry, ref))
        else:
            artifact = view.artifact(str(ref.artifact_id))
            if artifact is None:
                report("unknown_artifact", ref.written)
                continue
            designation = artifact.designation
            first, last = int(ref.line_start or 0), int(ref.line_end or 0)
            covering = packet.covering(artifact.artifact_id, first, last)
            if covering is None:
                report("not_retrieved", ref.written)
            else:
                spans.append(_contribution(covering, ref))
        cited.append(designation)
        if not policy.permits(designation, release_to):
            detail = f"{designation} exceeds {release_to}"
            report("designation_exceeds_channel", ref.written, detail)
    proven_quotations = proven_figures = 0
    said: list[str] = []
    if not claim.refs:
        report("uncited_claim")
    else:
        if claim.unbalanced is not None:
            report("unbalanced_quotation")
        masked = _masked(claim.text)
        for quotation in claim.quotations:
            gathered = [entry for entry in spans if quotation_in(quotation.text, entry.text)]
            found = [span for span in gathered if _in_one_turn(quotation.text, span.turns)]
            if gathered and not found:
                report("unsupported_quote", detail="spans turns")
                continue
            if not found:
                elsewhere = next(
                    (
                        e
                        for e in packet.entries
                        if quotation_in(quotation.text, e.text)
                        and _in_one_turn(quotation.text, _entry_turns(e))
                    ),
                    None,
                )
                if elsewhere is None:
                    report("unsupported_quote")
                else:
                    report("quote_wrong_source", detail=f"found in {elsewhere.handle}")
                continue
            proven_quotations += 1
            phrase, mention = speakers.attribution_phrase(
                masked[: quotation.offset - claim.offset]
            )
            if not phrase:
                continue
            if mention is None:
                if any(span.turns for span in found):
                    report("quote_wrong_speaker", detail="speaker not identified")
            elif any(mention.label in _labels(quotation.text, span.turns) for span in found):
                said.append(mention.label)
            else:
                speaker = speaker_of(quotation.text, found[0].turns)
                detail = f"said by {speaker}" if speaker else "no recorded speaker"
                report("quote_wrong_speaker", detail=detail)
        for figure in claim.figures:
            if any(figure_in(figure, span.text) for span in spans):
                proven_figures += 1
            else:
                report("unsupported_figure")
    proof = ClaimProof(
        claim=claim.index,
        line=line,
        column=column,
        kind=claim.kind,
        backed_by=tuple(dict.fromkeys(span.handle for span in spans)),
        quotations=proven_quotations,
        figures=proven_figures,
        speakers=tuple(dict.fromkeys(said)),
    )
    return proof, findings


def audit_answer(
    document: AnswerDocument,
    corpus: CompiledCorpus,
    policy: DisclosurePolicy,
    speakers: SpeakerRegistry,
    *,
    release_to: str | None = None,
) -> AnswerAudit:
    """Audit *document* against the packet its declared request rebuilds."""
    release_channel = document.channel if release_to is None else release_to
    if policy.ceiling(release_channel) is None:
        raise DisclosureError("unknown_channel", release_channel)
    packet = build_packet(
        corpus, policy, document.question, channel=document.channel, limit=document.limit
    )
    view = channel_view(corpus, policy, document.channel)
    findings: list[AuditFinding] = []
    if packet.digest != document.packet:
        findings.append(AuditFinding(document.packet_line, 1, 0, "packet_mismatch"))
    claims = split_claims(document.body)
    if not claims:
        findings.append(AuditFinding(document.body_start_line, 1, 0, "empty_answer"))
    proofs: list[ClaimProof] = []
    cited: list[str] = []
    for claim in claims:
        proof, claim_findings = _audit_claim(
            claim, document, packet, view, policy, speakers, release_channel, cited
        )
        proofs.append(proof)
        findings.extend(claim_findings)
    # The answer was written from the whole packet, so release joins every
    # entry's designation, not only the ones it cites.
    release = decide(policy, [e.designation for e in packet.entries] + cited, release_channel)
    if release.reason == "exceeds_ceiling" and not any(
        f.rule == "designation_exceeds_channel" for f in findings
    ):
        detail = f"packet {release.designation} exceeds {release_channel}"
        findings.append(
            AuditFinding(document.packet_line, 1, 0, "designation_exceeds_channel", "", detail)
        )
    return AnswerAudit(
        answer=document.path,
        channel=document.channel,
        release_to=release_channel,
        declared_packet=document.packet,
        rebuilt_packet=packet.digest,
        release=release,
        claims=tuple(proofs),
        findings=tuple(sorted(findings)),
    )
