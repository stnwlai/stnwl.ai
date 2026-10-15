"""Speaker-bound quotations over role-labelled transcript turns.

A transcript line ``LABEL: text`` opens a turn by that speaker; following
non-blank, non-heading lines continue it. A sentence that names a speaker with
a speech verb right before a quotation binds the quotation to that speaker, so
it must lie inside one turn by them. Names resolve on word boundaries, longest
alias first. Registry failures carry rule ids and counts, never alias text.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .compiler import CompiledCorpus
from .errors import SpeakerRegistryError
from .text import quotation_in

ATTRIBUTION_VERBS: tuple[str, ...] = (
    "admitted", "agreed", "answered", "asked", "conceded", "confirmed", "denied",
    "explained", "recalled", "replied", "responded", "said", "stated", "testified",
)
LABEL_LINE_RE = re.compile(r"^(?P<label>[A-Z]+(?: [A-Z]+)*): (?P<text>\S.*)$")
_LABEL_RE = re.compile(r"^[A-Z]+(?: [A-Z]+)*$")
_ALIAS_RE = re.compile(r"^[a-z]+(?: [a-z]+)*$")
_HEADING_RE = re.compile(r"^#{1,6}\s+\S")
_VERB_RE = re.compile(r"(?i)\s+(?:" + "|".join(ATTRIBUTION_VERBS) + r")\b")
_REGISTRY_KEYS = frozenset({"speakers", "version"})
_SPEAKER_KEYS = frozenset({"aliases", "label"})


@dataclass(frozen=True, slots=True)
class Speaker:
    label: str
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True, order=True)
class Mention:
    start: int
    end: int
    label: str
    alias: str


@dataclass(frozen=True, slots=True)
class Turn:
    label: str
    line_start: int
    line_end: int
    text: str


@lru_cache(maxsize=8)
def _mention_pattern(entries: tuple[tuple[str, str], ...]) -> re.Pattern[str]:
    # One named group per alias, so the match maps back to its alias without
    # re-casing the matched text. Order is longest first, then alphabetical.
    branches = "|".join(
        f"(?P<a{index}>" + r"\s+".join(map(re.escape, alias.split(" "))) + ")"
        for index, (alias, _label) in enumerate(entries)
    )
    return re.compile(r"(?i)(?<![0-9a-z])(?:" + branches + r")(?![0-9a-z])")


@dataclass(frozen=True, slots=True)
class SpeakerRegistry:
    speakers: tuple[Speaker, ...]

    def labels(self) -> frozenset[str]:
        return frozenset(speaker.label for speaker in self.speakers)

    def _entries(self) -> tuple[tuple[str, str], ...]:
        pairs = (
            (alias, speaker.label)
            for speaker in self.speakers
            for alias in speaker.aliases
        )
        return tuple(sorted(pairs, key=lambda pair: (-len(pair[0]), pair)))

    def mentions(self, text: str) -> tuple[Mention, ...]:
        """Non-overlapping alias mentions in *text*, leftmost and longest."""
        entries = self._entries()
        if not entries:
            return ()
        found: list[Mention] = []
        for match in _mention_pattern(entries).finditer(text):
            alias, label = entries[int(str(match.lastgroup)[1:])]
            found.append(Mention(match.start(), match.end(), label, alias))
        return tuple(found)

    def attribution(self, text: str) -> Mention | None:
        """The last mention followed directly by a speech verb, if any.

        Callers pass the claim text before the opening quotation mark, with
        citation brackets and earlier quotations blanked so offsets hold.
        """
        bound = [m for m in self.mentions(text) if _VERB_RE.match(text, m.end)]
        return bound[-1] if bound else None


def _invalid(detail: str) -> SpeakerRegistryError:
    return SpeakerRegistryError("registry_invalid", detail)


def _speaker(raw: object, position: int) -> Speaker:
    if not isinstance(raw, dict) or set(raw) - _SPEAKER_KEYS:
        raise _invalid(f"speaker {position} has unknown keys")
    label = raw.get("label")
    if not isinstance(label, str) or not _LABEL_RE.fullmatch(label):
        raise _invalid(f"speaker {position} label is not canonical")
    aliases = raw.get("aliases")
    if not isinstance(aliases, list) or not aliases:
        raise _invalid(f"speaker {position} has no aliases")
    if any(not isinstance(a, str) or not _ALIAS_RE.fullmatch(a) for a in aliases):
        raise _invalid(f"speaker {position} alias is not canonical")
    if len(set(aliases)) != len(aliases):
        raise _invalid(f"speaker {position} repeats an alias")
    return Speaker(label, tuple(sorted(aliases, key=lambda a: (-len(a), a))))


def load_speakers(path: Path) -> SpeakerRegistry:
    """Load a speaker registry and fail closed on any structural drift."""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise _invalid("speaker registry is unreadable") from exc
    if set(raw) - _REGISTRY_KEYS:
        raise _invalid("speaker registry has unknown keys")
    version = raw.get("version")
    if isinstance(version, bool) or version != 1:
        raise _invalid("unsupported speaker registry version")
    entries = raw.get("speakers")
    if not isinstance(entries, list) or not entries:
        raise _invalid("speaker registry has no speakers")
    speakers = [_speaker(entry, position) for position, entry in enumerate(entries, 1)]
    if len({speaker.label for speaker in speakers}) != len(speakers):
        raise _invalid("speaker labels are duplicated")
    owners: dict[str, set[str]] = {}
    for speaker in speakers:
        for alias in speaker.aliases:
            owners.setdefault(alias, set()).add(speaker.label)
    shared = sum(1 for labels in owners.values() if len(labels) > 1)
    if shared:
        raise SpeakerRegistryError("ambiguous_alias", f"{shared} shared")
    return SpeakerRegistry(tuple(sorted(speakers, key=lambda s: s.label)))


def speaker_turns(span: str, first_line: int) -> tuple[Turn, ...]:
    """Split *span*, whose first line is *first_line*, into labelled turns."""
    turns: list[Turn] = []
    current: Turn | None = None
    for offset, line in enumerate(span.split("\n")):
        number = first_line + offset
        match = LABEL_LINE_RE.match(line)
        if match:
            if current is not None:
                turns.append(current)
            current = Turn(match.group("label"), number, number, match.group("text"))
        elif current is not None and line.strip() and not _HEADING_RE.match(line):
            current = Turn(current.label, current.line_start, number, f"{current.text}\n{line}")
        elif current is not None:
            turns.append(current)
            current = None
    if current is not None:
        turns.append(current)
    return tuple(turns)


def speaker_of(quotation: str, turns: Sequence[Turn]) -> str | None:
    """The one label whose turns contain *quotation*; None if none or several."""
    labels = {turn.label for turn in turns if quotation_in(quotation, turn.text)}
    return labels.pop() if len(labels) == 1 else None


def unregistered_labels(
    corpus: CompiledCorpus, registry: SpeakerRegistry
) -> tuple[tuple[str, int], ...]:
    """``(artifact_id, line)`` for each transcript label the registry lacks."""
    known = registry.labels()
    return tuple(
        sorted(
            (artifact.artifact_id, artifact.body_start_line + index)
            for artifact in corpus.artifacts
            if artifact.artifact_type == "transcript"
            for index, line in enumerate(artifact.body.splitlines())
            if (match := LABEL_LINE_RE.match(line)) and match.group("label") not in known
        )
    )
