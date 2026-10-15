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
  starting with '#' is text. A heading with text is audited as a claim of its
  own, without its '#' markers or a closing '#' sequence; a bare '#' is
  structure. A leading '- ' or '* ' starts a paragraph and is excluded. So is
  a leading '<n>. ' or '<n>) ' (n of one to three digits), but only on a
  paragraph's first line or inside a paragraph that opened as a list item;
  elsewhere the line is text and n a figure.
- A paragraph whose every line starts with up to three spaces and '>' is a
  block quote: one claim whose quotation is its lines with the indent, '>' and
  one optional space stripped, minus trailing citation brackets. Only refs
  inside it back it. When it directly follows a paragraph whose last claim
  ends in ':', ignoring trailing citation brackets and whitespace, that claim
  is its lead-in; otherwise it has none.
- A paragraph that is one thematic break (three or more '-', '*' or '_', the
  same character, optionally spaced) is structure.
- A sentence ends at '.', '?', '!', U+3002 or U+FF0E outside quotations and
  outside citation brackets; a mark inside an ordinary bracket ends one too.
  After the mark, a run of '*', '_', '~', '`', ')', ']', U+2019, "'" and
  footnote markers '[^...]' is skipped; whitespace or the end of the
  paragraph must follow, so 'fire.The' stays one sentence. A closing quotation mark directly
  after one of those marks ends the sentence after the closing mark only when
  whitespace and then an uppercase letter, a citation bracket or the
  paragraph end follows. A '.' between digits never ends a sentence. There is
  no abbreviation list.
- Citation brackets that follow the end, after whitespace, belong to the
  sentence that just ended.

Answer grammar
- An answer may use plain paragraphs, '- ' and '* ' bullets and '<n>. ' or
  '<n>) ' items at the start of a line, headings, block quotes, standalone
  thematic breaks, inline emphasis ('*', '_', '~'), inline code spans (audited
  as ordinary text), and citation brackets with an optional link target.
- Anything else is unsupported_markup at its own position, in the claim that
  holds it: an HTML tag '<' plus a letter, '/', '!' or '?' up to the next '>';
  a character reference '&name', '&#digits' or '&#xhex', with or without ';';
  a footnote marker '[^...]', which also starts a footnote definition; any
  Unicode format character (category Cf), never stripped before matching; a
  backslash before ASCII punctuation, anywhere in the paragraph; a run of
  letters mixing ASCII letters with letters whose Unicode name starts with
  CYRILLIC or GREEK, at the run's start; an image '![...](...)'; a link
  '[...](...)' whose bracket is not citation-shaped; a thematic break inside
  a paragraph. Citation brackets and
  their link targets are not scanned for tags, references or footnotes. A
  paragraph that mixes '>' lines with other lines is reported once at its
  start. A '+' bullet, or any list marker after leading whitespace, is
  reported once per paragraph at its first such line, detail 'item'. The
  claim's other checks still run. A list item's number is not audited.

Quotations
- The pairs are straight double quotes, U+201C/U+201D, guillemets, fullwidth
  double quotes, and U+2018/U+2019, where the closing U+2019 is the first one
  not followed by a letter. Quotations count only outside citation brackets,
  and brackets inside a quotation are quoted text.
- An opening mark not closed in its paragraph is unbalanced_quotation, and that
  segment is not checked. So is any other quotation punctuation outside a
  pair: Unicode Pi or Pf, U+FF02, corner brackets U+300C-U+300F, or ornaments
  U+275D/U+275E. With no U+2018 open, a U+2019 after a letter or before a
  digit is an apostrophe.
- The ASCII single quote is never a quotation mark.

Citation brackets
- A closed bracket is citation-shaped when its content holds a handle or an
  address token, starts with an uppercase letter, holds no bracket, and
  contains a digit, or case-folds to a valid item list ('[s9]'). A directly
  following fragment anchor, '(#' then only ASCII letters, digits, '_' and '-'
  then ')', is a link target, part of it and not text; any other '(', a URL
  included, starts ordinary text. Other brackets ([sic], [emphasis added]) are ordinary text,
  and the quotations and figures inside them are checked.
- Items are separated by ',' or ';' with optional spaces. Each item is a
  handle S<n>, n from 1 to MAX_PACKET_LIMIT with no leading zero and no more
  digits than MAX_PACKET_LIMIT has, or an address
  <ID>:<start>[-<end>] in the retrieval grammar, without a pin, with start <=
  end.
- Any other citation-shaped bracket, including one holding a nested bracket,
  is malformed_citation and counts as no ref. Its finding names only the
  position of the first bad item.
- A handle token 'S<n>', an address token '<ID>:<digit>' or a bare artifact
  ID ('<ID>' ending in four digits, not followed by ':') outside quotations,
  citation brackets and link targets is malformed_citation at its own
  position, detail 'item 1'. Block quotes are quotations throughout.

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
- The lead-in is the claim text before the opening mark, or a block quote's
  lead-in claim, with citation brackets blanked, earlier
  quotations replaced by a placeholder that is neither a word nor whitespace,
  the contents of ordinary brackets and parentheses blanked, and '*', '_' and
  '~' read as spaces. So a mention before an earlier quotation never binds a
  speech verb after it. The attribution is
  speakers.attribution over it: the last speech verb binds the registered
  mention directly before it, separated only by whitespace and not after a
  possessive. With no speech verb there is no speaker check. A verb after the
  speech verb that is not one ('the exhibit was read') does not unbind it.
- Only a transcript record has turns, computed over the full entry text; a
  narrowed address keeps the turns that intersect its range. Any other record
  has none, whatever its lines look like.
- With a bound mention, some span the quotation is found in must have one turn
  by the mention's label holding it; otherwise quote_wrong_speaker, detail
  'said by <LABEL>' from the first such span's single speaker, or 'no recorded
  speaker'.
- With no bound mention, quote_wrong_speaker, detail 'speaker not identified',
  when any span the quotation is found in has speaker turns.

Figure check
- Figures are text.FIGURE_RE tokens outside quotations and citation brackets:
  an optionally signed number with an optional month before it and scale word
  after it, or a day before its month ('5th of March', '3rd day of March') or
  after 'the' ('March the 3rd'), read as month and day. Letters attached to a
  number are part of it, before and after an attached '%' or U+2030. Month names and the words 'of',
  'day of' and 'the' in those forms match in any case; months are full
  names, three-letter forms or 'Sept', each with an optional period; ordinal
  suffixes drop in any case. Claim and cited text alike are NFKC-folded
  first, so superscript and fullwidth digits are digits and U+00A0 a space;
  '*', '_' and '~' between a sign and a digit or between two digits are
  deleted, and elsewhere read as spaces. Each figure must satisfy
  text.figure_in for at least one contributed span, else unsupported_figure.
  Spelled-out numbers are not figures.

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
- Restricted prose: the whole body, with citation brackets, their link
  targets and heading markers blanked, and each of disclosure.restricted_lines
  for release_to are NFKC-folded and case-folded (each character together with
  the combining marks and Hangul conjoining jamo after it), with '*', '_',
  '~', '-', U+2010 to U+2015 and U+2212 read as spaces, curly quotation marks
  folded to ASCII and whitespace collapsed; each line also drops trailing
  '.?!;:,' and whitespace and counts only at 20 or more characters. Each
  occurrence is designation_exceeds_channel at the claim holding its start,
  or at its own position for the answer when no claim does, detail '<designation> text exceeds <release_to>', the join of those
  records' designations, which counts as cited. The question value is
  screened the same way; its occurrences are one answer-level finding at the
  question line and the column of the first, and their join counts as cited.
- The answer is releasable when disclosure.decide allows, on release_to, the
  join of every packet entry's designation and every cited designation.
  When that join exceeds release_to and no ref reported it, the answer gets
  designation_exceeds_channel at the packet line, detail 'packet
  <designation> exceeds <release_to>'.

Verdict
- Grounded means no finding other than designation_exceeds_channel; ok means
  grounded and releasable. No claims is empty_answer.

Findings sit at the line and column of the claim's first character, or claim 0
for answer-level findings; unsupported_markup and a loose handle, address or
artifact ID sit at their construct. They carry rule ids, refs as written,
handles, designations, channels and speaker labels, never quoted words,
figures or source text.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .attribution import SpeakerRegistry, Turn, speaker_of, speaker_turns
from .compiler import CompiledCorpus
from .disclosure import (
    Decision,
    DisclosurePolicy,
    channel_view,
    decide,
    restricted_lines,
)
from .errors import AnswerError, DisclosureError, FrontMatterError
from .frontmatter import parse_document
from .packet import MAX_PACKET_LIMIT, EvidencePacket, PacketEntry, build_packet
from .retrieval import ADDRESS_RE
from .text import figure_in, figure_tokens, quotation_in

RULES: tuple[str, ...] = (
    "uncited_claim", "malformed_citation", "unknown_handle", "unknown_artifact", "not_retrieved",
    "unbalanced_quotation", "unsupported_quote", "quote_wrong_source", "quote_wrong_speaker",
    "unsupported_figure", "packet_mismatch", "empty_answer", "designation_exceeds_channel",
    "unsupported_markup",
)
ANSWER_FIELDS = frozenset({"channel", "limit", "packet", "question"})
OPTIONAL_FIELDS = frozenset({"expect"})
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_LIMIT_RE = re.compile(r"^[1-9][0-9]?$")
_HANDLE_RE = re.compile(r"^S([1-9][0-9]*)$")
_BRACKET_RE = re.compile(r"^[A-Z][^\[\]]*$")
_CITATION_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])(?:S\d+|[A-Z][A-Z0-9_-]*\d{4}:\d)")
_ITEM_SEPARATOR_RE = re.compile(r"\s*[,;]\s*")
_LOOSE_REF_RE = re.compile(
    r"(?<![A-Za-z0-9])S[1-9]\d*(?![A-Za-z0-9])|[A-Z][A-Z0-9_-]*\d{4}:\d"
    r"|(?<![A-Za-z0-9])[A-Z][A-Z0-9_-]*\d{4}(?![A-Za-z0-9:])"
)
_HEADING_RE = re.compile(r" {0,3}#{1,6}(?:\s+|$)(?P<text>.*?)(?:\s+#+)?\s*$")
_ITEM_RE = re.compile(r"(?:[-*]|\d{1,3}[.)])\s")
_BREAK_RE = re.compile(r" {0,3}([-*_])(?: *\1){2,} *")
_QUOTE_LINE_RE = re.compile(r" {0,3}>")
_NESTED_ITEM_RE = re.compile(r"(?:\s+(?:[-*+]|\d{1,3}[.)])|\+)(?:\s|$)")
_TAG_RE = re.compile(r"<[A-Za-z/!?][^>]*>")
_REFERENCE_RE = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#[xX][0-9A-Fa-f]+);?")
_FOOTNOTE_RE = re.compile(r"\[\^[^\]\n]*\]")
_LINK_TARGET_RE = re.compile(r"\(#[A-Za-z0-9_-]*\)")
_ESCAPE_RE = re.compile(r"\\[!-/:-@\[-`{-~]")
_MIXED_SCRIPTS = ("CYRILLIC", "GREEK")
_EMPHASIS_RE = re.compile(r"[*_~]")
_SENTENCE_MARKS = ".?!\u3002\uff0e"
_AFTER_MARK = "*_~`)]\u2019'"
_PROSE_FOLD = str.maketrans(
    {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
     **dict.fromkeys("-\u2010\u2011\u2012\u2013\u2014\u2015\u2212", " ")}
)
_PROSE_END = ".?!;:, "
_MIN_PROSE_CHARS = 20
_JAMO = (("\u1160", "\u11ff"), ("\ud7b0", "\ud7ff"))  # conjoining vowels and finals
_PLACEHOLDER = "\x00"  # an earlier quotation in a lead-in: no word, no gap
_STRAY_MARKS = "\u300c\u300d\u300e\u300f\u275d\u275e"
_ASIDES = {"]": "[", ")": "("}
_CLOSERS = {
    '"': '"', "\u201c": "\u201d", "\u00ab": "\u00bb", "\uff02": "\uff02", "\u2018": "\u2019",
}


@dataclass(frozen=True, slots=True)
class AnswerDocument:
    path: str
    question: str
    question_line: int
    question_column: int  # of the question value's first character
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
    lead: str  # the lead-in, blanked for speaker binding


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
    markup: tuple[tuple[int, str], ...]  # body offset and detail of each refused construct
    loose: tuple[int, ...]  # body offset of each handle or address outside brackets

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
    packet_line, question_line = (
        next(
            number
            for number, line in enumerate(parsed.lines, start=1)
            if line.split(":", 1)[0].strip() == key
        )
        for key in ("packet", "question")
    )
    asked = parsed.lines[question_line - 1]
    return AnswerDocument(
        path=source,
        question=metadata["question"],
        question_line=question_line,
        question_column=asked.index(metadata["question"], asked.index(":") + 1) + 1,
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
    """Whether ``text[index]`` is quotation punctuation, not an apostrophe.

    Callers ask only outside quotations, so no U+2018 is open.
    """
    character = text[index]
    if character in ('"', "\uff02") or character in _STRAY_MARKS:
        return True
    if unicodedata.category(character) not in ("Pi", "Pf"):
        return False
    return not (
        character == "\u2019"
        and ((index and text[index - 1].isalpha()) or text[index + 1 : index + 2].isdecimal())
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
    return (
        _CITATION_TOKEN_RE.search(content) is not None
        or (
            _BRACKET_RE.fullmatch(content) is not None
            and any(character.isdigit() for character in content)
        )
        or all(  # '[s9]' is a miscased ref
            _HANDLE_RE.fullmatch(item) or ADDRESS_RE.fullmatch(item)
            for item in _ITEM_SEPARATOR_RE.split(content.upper())
        )
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
                if (target := _LINK_TARGET_RE.match(text, end)) is not None:
                    end = target.end()  # a Markdown link target is not text
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
    """Citations, quotations, and an unclosed quotation's tail."""
    tail = [(layout.opened, len(text))] if layout.opened is not None else []
    return [*layout.citations, *layout.quotations, *tail]


def _masked(text: str, quoted: str = " ") -> str:
    """*text* with every hidden span blanked, so offsets hold.

    Quotations fill with *quoted*, other hidden spans with spaces.
    """
    layout = _layout(text)
    characters = list(text)
    for start, end in _hidden_spans(text, layout):
        characters[start:end] = " " * (end - start)
    for start, end in layout.quotations:
        characters[start:end] = quoted * (end - start)
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
        if (
            handle is not None
            and len(handle.group(1)) <= len(str(MAX_PACKET_LIMIT))
            and int(handle.group(1)) <= MAX_PACKET_LIMIT
        ):
            refs.append(CitationRef(item, at, item, None, None, None))
            continue
        match = ADDRESS_RE.fullmatch(item)
        if match is None or match.group("pin") is not None:
            return (), number
        try:
            start = int(match.group("start"))
            end = int(match.group("end") or start)
        except ValueError:  # more digits than int() will read
            return (), number
        if end < start:
            return (), number
        refs.append(CitationRef(item, at, None, match.group("id"), start, end))
    return tuple(refs), 0


def _paragraphs(body: str) -> list[tuple[int, int]]:
    """Paragraph spans; a heading with text is a paragraph of its own."""
    spans: list[tuple[int, int]] = []
    start: int | None = None
    listed = False  # the open paragraph's first line was a list item
    end = 0
    offset = 0
    for line in body.split("\n"):
        heading = _HEADING_RE.match(line)
        item = None if heading or _BREAK_RE.fullmatch(line) else _ITEM_RE.match(line)
        if item and line[0].isdigit() and start is not None and not listed:
            item = None  # inside a paragraph, '<n>) ' is text and n a figure
        if not line.strip() or heading or item:
            if start is not None:
                spans.append((start, end))
            start = offset + item.end() if item else None
            listed = item is not None
            if heading and heading.group("text"):
                spans.append((offset + heading.start("text"), offset + heading.end("text")))
        elif start is None:
            start = offset
        end = offset + len(line)
        offset += len(line) + 1
    if start is not None:
        spans.append((start, end))
    return spans


def _sentences(text: str) -> list[tuple[int, int]]:
    """Sentence spans of one paragraph, each with its trailing citation brackets."""
    layout = _layout(text)
    hidden = [False] * len(text)
    for low, high in _hidden_spans(text, layout):
        hidden[low:high] = [True] * (high - low)
    bracketed = [False] * len(text)
    for low, high in layout.citations:
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
            elif skipped := _FOOTNOTE_RE.match(text, end):
                end = skipped.end()
            else:
                break
        # Whitespace or the paragraph end must follow, so a '.' between digits
        # never ends a sentence.
        if end < len(text) and not text[end].isspace():
            return None
        # After a closing quotation mark, only a capital or a citation starts
        # the next sentence.
        following = len(text) - len(text[end:].lstrip())
        if (
            index in closing
            and following < len(text)
            and not (text[following].isupper() or following in trailing)
        ):
            return None
        return end

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
    """A block quote's text: indent, '>' and one space stripped, minus trailing citations."""
    quoted = "\n".join(re.sub(r"^ {0,3}> ?", "", line) for line in paragraph.split("\n"))
    starts = {high: low for low, high in _layout(quoted).citations}
    end = len(quoted.rstrip())
    while True:
        if end in starts:
            end = len(quoted[: starts[end]].rstrip())
        elif end and quoted[end - 1] in _SENTENCE_MARKS and end - 1 in starts:
            end -= 1
        else:
            return quoted[:end]


def _lead_in(prefix: str) -> str:
    """*prefix*, already masked, with aside contents and emphasis blanked."""
    characters = list(_EMPHASIS_RE.sub(" ", prefix))
    openers: list[int] = []
    for index, character in enumerate(characters):
        if character in "[(":
            openers.append(index)
        elif openers and characters[openers[-1]] == _ASIDES.get(character):
            low = openers.pop()
            characters[low + 1 : index] = " " * (index - low - 1)
    return "".join(characters)


def _block_lead(prior: str) -> str:
    """A block quote's lead-in from the claim just before it, if that ends in ':'."""
    masked = _masked(prior, _PLACEHOLDER).rstrip()  # trailing citations read as spaces
    return _lead_in(masked) if masked.endswith(":") else ""


def _markup(paragraph: str) -> list[tuple[int, str]]:
    """Offsets and details of the constructs outside the answer grammar."""
    layout = _layout(paragraph)
    scanned = list(paragraph)
    for low, high in layout.citations:
        scanned[low:high] = " " * (high - low)
    found = [
        (match.start(), "")
        for pattern in (_TAG_RE, _REFERENCE_RE, _FOOTNOTE_RE)
        for match in pattern.finditer("".join(scanned))
    ]
    found.extend(
        (index, "") for index, character in enumerate(paragraph)
        if unicodedata.category(character) == "Cf"
    )
    found.extend((match.start(), "") for match in _ESCAPE_RE.finditer(paragraph))
    found.extend(
        (start, "") for start, word in _words(paragraph) if _mixed_script(word)
    )
    plain = set(layout.brackets)
    for low, _high in (*layout.citations, *layout.brackets):
        close = _matching(paragraph, low)
        if close is None or not paragraph.startswith("(", close + 1):
            continue
        if low and paragraph[low - 1] == "!":
            found.append((low - 1, ""))  # an image
        elif (low, close + 1) in plain:
            found.append((low, ""))  # a link that is not a citation
    lines = paragraph.split("\n")
    quoted = [_QUOTE_LINE_RE.match(line) is not None for line in lines]
    if any(quoted) and not all(quoted):
        found.append((0, ""))  # a lazy block-quote line
    offset = 0
    nested = False
    for line in lines:
        if len(lines) > 1 and _BREAK_RE.fullmatch(line):
            found.append((offset + len(line) - len(line.lstrip()), ""))
        elif not nested and _NESTED_ITEM_RE.match(line):
            nested = True  # a nested, indented or '+' list, reported once
            found.append((offset + len(line) - len(line.lstrip()), "item"))
        offset += len(line) + 1
    return found


def _words(text: str) -> Iterator[tuple[int, str]]:
    """Runs of letters in *text*, with any combining mark kept inside its word."""
    start: int | None = None
    for index, character in enumerate(f"{text} "):
        inside = character.isalpha() or (
            start is not None and unicodedata.category(character).startswith("M")
        )
        if inside and start is None:
            start = index
        elif not inside and start is not None:
            yield start, text[start:index]
            start = None


def _mixed_script(word: str) -> bool:
    """Whether *word*, all letters, mixes ASCII with Cyrillic or Greek letters."""
    return any(character.isascii() for character in word) and any(
        unicodedata.name(character, "").startswith(_MIXED_SCRIPTS) for character in word
    )


def _within(
    found: list[tuple[int, str]], low: int, high: int, base: int
) -> tuple[tuple[int, str], ...]:
    """The constructs at paragraph offsets *low* to *high*, as body offsets."""
    return tuple(sorted((base + at, detail) for at, detail in found if low <= at < high))


def split_claims(body: str) -> tuple[Claim, ...]:
    """Split an answer body into claims with their refs, quotations and figures."""
    claims: list[Claim] = []
    previous_end = 0
    for paragraph_start, paragraph_end in _paragraphs(body):
        paragraph = body[paragraph_start:paragraph_end]
        if _BREAK_RE.fullmatch(paragraph):
            continue  # a thematic break is structure
        adjacent = bool(claims) and not body[previous_end:paragraph_start].strip()
        previous_end = paragraph_end
        found = _markup(paragraph)
        lines = paragraph.split("\n")
        if all(_QUOTE_LINE_RE.match(line) for line in lines):
            refs, malformed = _refs(paragraph, _layout(paragraph), paragraph_start)
            quoted = _block_quotation(paragraph)
            lead = _block_lead(claims[-1].text) if adjacent else ""
            claims.append(
                Claim(
                    index=len(claims) + 1,
                    offset=paragraph_start,
                    text=paragraph,
                    refs=tuple(refs),
                    malformed=tuple(malformed),
                    quotations=(
                        (Quotation(quoted, paragraph_start, lead),) if quoted.strip() else ()
                    ),
                    figures=(),
                    unbalanced=None,
                    markup=_within(found, 0, len(paragraph), paragraph_start),
                    loose=(),
                )
            )
            continue
        sentences = _sentences(paragraph)
        for number, (start, end) in enumerate(sentences):
            text = paragraph[start:end]
            layout = _layout(text)
            base = paragraph_start + start
            refs, malformed = _refs(text, layout, base)
            masked = _masked(text)
            lead = _masked(text, _PLACEHOLDER)
            later = sentences[number + 1 :]
            next_start = later[0][0] if later else len(paragraph)
            claims.append(
                Claim(
                    index=len(claims) + 1,
                    offset=base,
                    text=text,
                    refs=tuple(refs),
                    malformed=tuple(malformed),
                    quotations=tuple(
                        Quotation(text[open_ + 1 : close - 1], base + open_,
                                  _lead_in(lead[:open_]))
                        for open_, close in layout.quotations
                    ),
                    figures=figure_tokens(masked),
                    unbalanced=None if layout.unbalanced is None else base + layout.unbalanced,
                    markup=_within(found, start if number else 0, next_start, paragraph_start),
                    loose=tuple(base + m.start() for m in _LOOSE_REF_RE.finditer(masked)),
                )
            )
    return tuple(claims)


@dataclass(frozen=True, slots=True)
class _Span:
    """The text one ref contributes, with the turns that ref may speak for."""

    handle: str
    text: str
    turns: tuple[Turn, ...]


def _entry_turns(entry: PacketEntry, view: CompiledCorpus) -> tuple[Turn, ...]:
    """Speaker turns of a transcript entry; any other record has none."""
    artifact = view.artifact(entry.hit.citation.artifact_id)
    if artifact is None or artifact.artifact_type != "transcript":
        return ()
    return speaker_turns(entry.text, entry.hit.citation.line_start)


def _labels(quotation: str, turns: tuple[Turn, ...]) -> set[str]:
    """Labels of the turns that each contain *quotation* whole."""
    return {turn.label for turn in turns if quotation_in(quotation, turn.text)}


def _in_one_turn(quotation: str, turns: tuple[Turn, ...]) -> bool:
    """Whether a span with turns holds *quotation* inside one turn; no turns passes."""
    return not turns or bool(_labels(quotation, turns))


def _contribution(entry: PacketEntry, ref: CitationRef, view: CompiledCorpus) -> _Span:
    first = entry.hit.citation.line_start
    turns = _entry_turns(entry, view)
    if ref.line_start is None or ref.line_end is None:
        return _Span(entry.handle, entry.text, turns)
    lines = entry.text.split("\n")[ref.line_start - first : ref.line_end - first + 1]
    return _Span(
        entry.handle,
        "\n".join(lines),
        tuple(t for t in turns if t.line_start <= ref.line_end and t.line_end >= ref.line_start),
    )


def _joins(character: str) -> bool:
    """Whether *character* normalizes together with the character before it."""
    return bool(unicodedata.combining(character)) or any(
        low <= character <= high for low, high in _JAMO
    )


def _prose(text: str) -> tuple[str, tuple[int, ...]]:
    """*text* folded for restricted-line matching, with each character's offset.

    Each character, with the combining marks and Hangul conjoining jamo after
    it, is NFKC-folded and case-folded, '*', '_', '~' and dashes read as spaces,
    curly quotation marks fold to ASCII, and whitespace runs collapse to one
    space.
    """
    folded: list[str] = []
    origins: list[int] = []
    index = 0
    while index < len(text):
        end = index + 1
        while end < len(text) and _joins(text[end]):
            end += 1
        piece = unicodedata.normalize("NFKC", text[index:end]).translate(_PROSE_FOLD).casefold()
        for character in _EMPHASIS_RE.sub(" ", piece):
            if character.isspace():
                if not folded or folded[-1] == " ":
                    continue
                character = " "
            folded.append(character)
            origins.append(index)
        index = end
    if folded and folded[-1] == " ":
        folded.pop()
        origins.pop()
    return "".join(folded), tuple(origins)


def _copied(
    body: str, claims: tuple[Claim, ...], restricted: tuple[tuple[str, str], ...]
) -> list[tuple[int, int, str]]:
    """Claim index (0 when none holds it), body offset and designation of each
    restricted line the answer body copies.

    Citation brackets and their link targets are blanked first, so a match may
    cross them and the claims they end, and so are heading markers, so a copied
    heading is found once, in its claim.
    """
    characters = list(body)
    for claim in claims:
        for low, high in _layout(claim.text).citations:
            characters[claim.offset + low : claim.offset + high] = " " * (high - low)
    offset = 0
    for line in body.split("\n"):
        if heading := _HEADING_RE.match(line):
            for low, high in ((0, heading.start("text")), (heading.end("text"), len(line))):
                characters[offset + low : offset + high] = " " * (high - low)
        offset += len(line) + 1
    return [
        (next((c.index for c in claims if c.offset <= at < c.offset + len(c.text)), 0), at, d)
        for at, d in _occurrences("".join(characters), restricted)
    ]


def _occurrences(
    text: str, restricted: tuple[tuple[str, str], ...]
) -> list[tuple[int, str]]:
    """Offset in *text* and designation of each restricted line it copies."""
    haystack, origins = _prose(text)
    found: list[tuple[int, str]] = []
    for designation, line in restricted:
        needle = _prose(line)[0].rstrip(_PROSE_END)
        if len(needle) < _MIN_PROSE_CHARS:
            continue
        start = haystack.find(needle)
        while start != -1:
            found.append((origins[start], designation))
            start = haystack.find(needle, start + 1)
    return found


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
    copied: str | None,
    cited: list[str],
) -> tuple[ClaimProof, list[AuditFinding]]:
    line, column = _position(document, claim.offset)
    findings: list[AuditFinding] = []

    def report(rule: str, ref: str = "", detail: str = "") -> None:
        findings.append(AuditFinding(line, column, claim.index, rule, ref, detail))

    for offset, detail in claim.markup:
        at_line, at_column = _position(document, offset)
        findings.append(
            AuditFinding(at_line, at_column, claim.index, "unsupported_markup", "", detail)
        )
    for item in claim.malformed:
        report("malformed_citation", detail=f"item {item}")
    for offset in claim.loose:
        at_line, at_column = _position(document, offset)
        findings.append(
            AuditFinding(at_line, at_column, claim.index, "malformed_citation", "", "item 1")
        )
    if copied is not None:
        cited.append(copied)
        report("designation_exceeds_channel", detail=f"{copied} text exceeds {release_to}")
    spans: list[_Span] = []
    for ref in claim.refs:
        if ref.handle is not None:
            entry = packet.entry(ref.handle)
            if entry is None:
                report("unknown_handle", ref.written)
                continue
            designation = entry.designation
            spans.append(_contribution(entry, ref, view))
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
                spans.append(_contribution(covering, ref, view))
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
                        and _in_one_turn(quotation.text, _entry_turns(e, view))
                    ),
                    None,
                )
                if elsewhere is None:
                    report("unsupported_quote")
                else:
                    report("quote_wrong_source", detail=f"found in {elsewhere.handle}")
                continue
            proven_quotations += 1
            verb, mention = speakers.attribution(quotation.lead)
            if not verb:
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
    designations = {artifact.artifact_id: artifact.designation for artifact in corpus.artifacts}
    restricted = tuple(
        (designations[artifact_id], text)
        for artifact_id, text in restricted_lines(corpus, policy, release_channel)
    )
    copies = _copied(document.body, claims, restricted)
    for claim in claims:
        copied = policy.join(d for index, _offset, d in copies if index == claim.index)
        proof, claim_findings = _audit_claim(
            claim, document, packet, view, policy, speakers, release_channel, copied, cited
        )
        proofs.append(proof)
        findings.extend(claim_findings)
    asked = _occurrences(document.question, restricted)
    if (joined := policy.join(d for _offset, d in asked)) is not None:
        cited.append(joined)
        column = document.question_column + min(offset for offset, _d in asked)
        detail = f"{joined} text exceeds {release_channel}"
        findings.append(
            AuditFinding(document.question_line, column, 0, "designation_exceeds_channel", "",
                         detail)
        )
    for offset, designation in sorted({(o, d) for index, o, d in copies if not index}):
        line, column = _position(document, offset)
        cited.append(designation)
        detail = f"{designation} text exceeds {release_channel}"
        findings.append(
            AuditFinding(line, column, 0, "designation_exceeds_channel", "", detail)
        )
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
