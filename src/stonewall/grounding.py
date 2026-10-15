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
- Body paragraphs split at blank lines. Lines starting with '#' are structure,
  not claims. A leading '- ' or '* ' starts a paragraph and is excluded.
- A sentence ends at '.', '?' or '!' outside quotations and outside brackets,
  when followed by whitespace or the end of the paragraph. A closing quotation
  mark directly after one of those marks ends the sentence after the mark. A
  '.' between digits never ends a sentence. There is no abbreviation list.
- Citation brackets that follow the end, after whitespace, belong to the
  sentence that just ended.

Quotations
- Straight double quotes toggle; curly quotes pair. Quotations count only
  outside brackets, and brackets inside a quotation are quoted text.
- An opening mark not closed in its paragraph is unbalanced_quotation, and that
  segment is not checked.

Citation brackets
- A bracket is citation-shaped when it is not immediately followed by '(', its
  content starts with an uppercase letter and holds no bracket, and its content
  contains a digit. Other brackets ([sic], [emphasis added]) are ignored.
- Items are separated by ',' with optional spaces. Each item is a handle S<n>,
  n from 1 to 20 with no leading zero, or an address <ID>:<start>[-<end>] in
  the retrieval grammar, without a pin, with start <= end.
- Any other citation-shaped bracket is malformed_citation and counts as no
  ref. Its finding names only the position of the first bad item.

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
- Found verbatim (text.quotation_in) in a contributed span: proven, then
  speaker-checked.
- Else found in any packet entry's full text, including the same entry outside
  a narrowed range: quote_wrong_source, detail 'found in S<n>', the first such
  entry in rank order.
- Else unsupported_quote.

Speaker check
- The attribution is speakers.attribution over the claim text before the
  opening mark, with brackets and earlier quotations blanked so offsets hold.
- Turns are computed over the full entry text; a narrowed address keeps the
  turns that intersect its range. When an attribution exists and speaker_of
  differs from its label: quote_wrong_speaker, detail 'said by <LABEL>', or 'no
  recorded speaker' when there are no turns or no single speaker.
- A quotation with no attribution phrase is not speaker-checked.

Figure check
- Figures are text.FIGURE_RE tokens outside quotations and brackets. Each must
  satisfy text.figure_in for at least one contributed span, else
  unsupported_figure. Spelled-out numbers are not figures.

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
- The answer is releasable when disclosure.decide allows the join of every
  such designation on release_to. No resolved ref means no release.

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
from .text import FIGURE_RE, figure_in, quotation_in

RULES: tuple[str, ...] = (
    "uncited_claim", "malformed_citation", "unknown_handle", "unknown_artifact", "not_retrieved",
    "unbalanced_quotation", "unsupported_quote", "quote_wrong_source", "quote_wrong_speaker",
    "unsupported_figure", "packet_mismatch", "empty_answer", "designation_exceeds_channel",
)
ANSWER_FIELDS = frozenset({"channel", "limit", "packet", "question"})
OPTIONAL_FIELDS = frozenset({"expect"})
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_LIMIT_RE = re.compile(r"^[1-9][0-9]?$")
_HANDLE_RE = re.compile(r"^S(?:[1-9]|1[0-9]|20)$")
_BRACKET_RE = re.compile(r"^[A-Z][^\[\]]*$")
_ITEM_SEPARATOR_RE = re.compile(r"\s*,\s*")
_SENTENCE_MARKS = ".?!"
_CLOSERS = {'"': '"', "\u201c": "\u201d"}


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


def _structure(text: str) -> tuple[list[tuple[int, int]], list[tuple[int, int]], int | None]:
    """Brackets and quotations as ``(start, end)`` spans, plus any unclosed mark."""
    brackets: list[tuple[int, int]] = []
    quotations: list[tuple[int, int]] = []
    opened: int | None = None
    index = 0
    while index < len(text):
        character = text[index]
        if opened is not None:
            if character == _CLOSERS[text[opened]]:
                quotations.append((opened, index + 1))
                opened = None
        elif character == "[":
            close = text.find("]", index + 1)
            nested = text.find("[", index + 1)
            if close != -1 and (nested == -1 or nested > close):
                brackets.append((index, close + 1))
                index = close + 1
                continue
        elif character in _CLOSERS:
            opened = index
        index += 1
    return brackets, quotations, opened


def _hidden(text: str) -> list[tuple[int, int]]:
    """Spans of brackets, quotations, and an unclosed quotation's tail."""
    brackets, quotations, opened = _structure(text)
    return brackets + quotations + ([(opened, len(text))] if opened is not None else [])


def _masked(text: str) -> str:
    """*text* with every hidden span blanked to spaces, so offsets hold."""
    characters = list(text)
    for start, end in _hidden(text):
        characters[start:end] = " " * (end - start)
    return "".join(characters)


def _citation_shaped(text: str, start: int, end: int) -> bool:
    content = text[start + 1 : end - 1]
    return (
        not text.startswith("(", end)
        and _BRACKET_RE.fullmatch(content) is not None
        and any(character.isdigit() for character in content)
    )


def _parse_items(content: str, offset: int) -> tuple[tuple[CitationRef, ...], int]:
    """Refs in one bracket, or ``((), k)`` for its first bad item k (1-based)."""
    refs: list[CitationRef] = []
    position = 0
    for number, item in enumerate(_ITEM_SEPARATOR_RE.split(content), start=1):
        position = content.find(item, position) if item else position
        at = offset + position
        position += len(item)
        if _HANDLE_RE.fullmatch(item):
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


def _paragraphs(body: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start: int | None = None
    end = 0
    offset = 0
    for line in body.split("\n"):
        item = line.startswith(("- ", "* "))
        if not line.strip() or line.startswith("#") or item:
            if start is not None:
                spans.append((start, end))
            start = offset + 2 if item else None
        elif start is None:
            start = offset
        end = offset + len(line)
        offset += len(line) + 1
    if start is not None:
        spans.append((start, end))
    return spans


def _sentences(text: str) -> list[tuple[int, int]]:
    """Sentence spans of one paragraph, each with its trailing citation brackets."""
    brackets, quotations, _opened = _structure(text)
    hidden = [False] * len(text)
    for low, high in _hidden(text):
        hidden[low:high] = [True] * (high - low)
    closing = {high - 1 for _low, high in quotations}
    trailing = {low: high for low, high in brackets if _citation_shaped(text, low, high)}

    def ends_at(index: int) -> bool:
        # A mark needs whitespace or the paragraph end after it, so a '.'
        # between digits never ends a sentence.
        if index + 1 < len(text) and not text[index + 1].isspace():
            return False
        if index in closing:
            return text[index - 1] in _SENTENCE_MARKS
        return not hidden[index] and text[index] in _SENTENCE_MARKS

    spans: list[tuple[int, int]] = []
    start: int | None = None
    for index in range(len(text)):
        if start is None:
            if index >= (spans[-1][1] if spans else 0) and not text[index].isspace():
                start = index
            continue
        if not ends_at(index):
            continue
        end = index + 1
        while (following := len(text) - len(text[end:].lstrip())) in trailing:
            end = trailing[following]
        if end > index + 1 and end < len(text) and ends_at(end) and end not in closing:
            end += 1  # '"Quoted." [S1].' keeps its final mark
        spans.append((start, end))
        start = None
    if start is not None:
        spans.append((start, len(text.rstrip())))
    return spans


def split_claims(body: str) -> tuple[Claim, ...]:
    """Split an answer body into claims with their refs, quotations and figures."""
    claims: list[Claim] = []
    for paragraph_start, paragraph_end in _paragraphs(body):
        paragraph = body[paragraph_start:paragraph_end]
        for start, end in _sentences(paragraph):
            text = paragraph[start:end]
            brackets, quotations, opened = _structure(text)
            base = paragraph_start + start
            refs: list[CitationRef] = []
            malformed: list[int] = []
            for bracket_start, bracket_end in brackets:
                if not _citation_shaped(text, bracket_start, bracket_end):
                    continue
                found, bad = _parse_items(
                    text[bracket_start + 1 : bracket_end - 1], base + bracket_start + 1
                )
                refs.extend(found)
                if bad:
                    malformed.append(bad)
            claims.append(
                Claim(
                    index=len(claims) + 1,
                    offset=base,
                    text=text,
                    refs=tuple(refs),
                    malformed=tuple(malformed),
                    quotations=tuple(
                        Quotation(text[open_ + 1 : close - 1], base + open_)
                        for open_, close in quotations
                    ),
                    figures=tuple(m.group(0) for m in FIGURE_RE.finditer(_masked(text))),
                    unbalanced=None if opened is None else base + opened,
                )
            )
    return tuple(claims)


@dataclass(frozen=True, slots=True)
class _Span:
    """The text one ref contributes, with the turns that ref may speak for."""

    handle: str
    text: str
    turns: tuple[Turn, ...]


def _contribution(entry: PacketEntry, ref: CitationRef) -> _Span:
    first = entry.hit.citation.line_start
    turns = speaker_turns(entry.text, first)
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
            found = next(
                (entry for entry in spans if quotation_in(quotation.text, entry.text)), None
            )
            if found is None:
                elsewhere = next(
                    (e for e in packet.entries if quotation_in(quotation.text, e.text)), None
                )
                if elsewhere is None:
                    report("unsupported_quote")
                else:
                    report("quote_wrong_source", detail=f"found in {elsewhere.handle}")
                continue
            proven_quotations += 1
            mention = speakers.attribution(masked[: quotation.offset - claim.offset])
            if mention is None:
                continue
            speaker = speaker_of(quotation.text, found.turns)
            if speaker == mention.label:
                said.append(speaker)
            else:
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
    return AnswerAudit(
        answer=document.path,
        channel=document.channel,
        release_to=release_channel,
        declared_packet=document.packet,
        rebuilt_packet=packet.digest,
        release=decide(policy, cited, release_channel),
        claims=tuple(proofs),
        findings=tuple(sorted(findings)),
    )
