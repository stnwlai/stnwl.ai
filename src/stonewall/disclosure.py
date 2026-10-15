"""Designation flow control: which records may reach which output channel.

Designations are totally ordered, least to most restrictive; the reference
policy declares public < confidential < privileged. Each channel has a ceiling,
the most restrictive designation it may carry, and a record is releasable on a
channel when its designation ranks at or below that ceiling.

Anything derived from several records carries the join: the most restrictive
designation among its sources.

Fail closed. An unknown designation (exact string match, so a case variant is
unknown), an unknown channel, and an empty source set all deny. A view refuses
outright while any record carries an unknown designation, and views filter
records before scoring, so a record above the ceiling never enters document
frequencies or average length.

The fixed decisions live in code, not in the policy file, so editing the file
can neither open privileged records to the model channel nor confidential
records to the publish channel, and reordering the designations is caught.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .compiler import CompiledCorpus, corpus_root_digest
from .errors import DisclosureError
from .hashing import canonical_json_bytes, sha256_bytes
from .text import collapse_whitespace, markdown_headings

FIXED_DECISIONS: tuple[tuple[str, str, bool], ...] = (
    ("public", "publish", True),
    ("confidential", "publish", False),
    ("privileged", "model", False),
    ("privileged", "publish", False),
    ("privileged", "review", True),
)
FIXED_ORDER = ("public", "confidential", "privileged")
PUBLISH_CHANNEL = "publish"
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_POLICY_KEYS = frozenset({"ceilings", "designations", "version"})
_MIN_LINE_CHARS = 20


@dataclass(frozen=True, slots=True)
class DisclosurePolicy:
    designations: tuple[str, ...]
    ceilings: tuple[tuple[str, str], ...]

    def rank(self, designation: str) -> int | None:
        """Position from least restrictive, or None for an undeclared label."""
        if designation not in self.designations:
            return None
        return self.designations.index(designation)

    def ceiling(self, channel: str) -> str | None:
        return dict(self.ceilings).get(channel)

    @property
    def channels(self) -> tuple[str, ...]:
        return tuple(channel for channel, _designation in self.ceilings)

    def permits(self, designation: str, channel: str) -> bool:
        """Whether *designation* is releasable on *channel*; unknowns deny."""
        ceiling = self.ceiling(channel)
        rank = self.rank(designation)
        if ceiling is None or rank is None:
            return False
        limit = self.rank(ceiling)
        return limit is not None and rank <= limit

    def join(self, designations: Iterable[str]) -> str | None:
        """The most restrictive designation, or None if empty or any is unknown."""
        ranks = [self.rank(designation) for designation in designations]
        if not ranks or any(rank is None for rank in ranks):
            return None
        return self.designations[max(rank for rank in ranks if rank is not None)]

    def to_dict(self) -> dict[str, Any]:
        return {"ceilings": dict(self.ceilings), "designations": list(self.designations)}

    @property
    def digest(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.to_dict()))


@dataclass(frozen=True, slots=True)
class Decision:
    channel: str
    designation: str | None
    allowed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "channel": self.channel,
            "designation": self.designation,
            "reason": self.reason,
        }


def load_policy(path: Path) -> DisclosurePolicy:
    """Load a policy file and refuse any shape or decision it may not take."""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise DisclosureError("policy_invalid", "policy file is unreadable") from exc
    if set(raw) - _POLICY_KEYS:
        raise DisclosureError("policy_invalid", "unknown top-level key")
    version = raw.get("version")
    if type(version) is not int or version != 1:
        raise DisclosureError("policy_invalid", "unsupported version")
    designations = raw.get("designations")
    if (
        not isinstance(designations, list)
        or not designations
        or not all(
            isinstance(item, str) and _NAME_RE.fullmatch(item) for item in designations
        )
        or len(set(designations)) != len(designations)
    ):
        raise DisclosureError(
            "policy_invalid", "designations must be unique lowercase names"
        )
    ceilings = raw.get("ceilings")
    if not isinstance(ceilings, dict):
        raise DisclosureError("policy_invalid", "ceilings must be a table")
    for channel, ceiling in ceilings.items():
        if not _NAME_RE.fullmatch(channel) or not isinstance(ceiling, str):
            raise DisclosureError("policy_invalid", "ceilings must map names to names")
        if ceiling not in designations:
            raise DisclosureError("unknown_ceiling", channel)
    policy = DisclosurePolicy(
        designations=tuple(designations),
        ceilings=tuple(sorted(ceilings.items())),
    )
    ranks = [policy.rank(designation) for designation in FIXED_ORDER]
    if None not in ranks and ranks != sorted(ranks):
        raise DisclosureError("fixed_decision_violated", "designation order")
    for designation, channel, expected in FIXED_DECISIONS:
        if (
            policy.rank(designation) is None
            or policy.ceiling(channel) is None
            or policy.permits(designation, channel) != expected
        ):
            raise DisclosureError(
                "fixed_decision_violated", f"{designation} {channel}"
            )
    return policy


def decide(policy: DisclosurePolicy, designations: Iterable[str], channel: str) -> Decision:
    """Decide release of material derived from *designations* onto *channel*."""
    sources = tuple(designations)
    joined = policy.join(sources)
    if policy.ceiling(channel) is None:
        reason = "unknown_channel"
    elif not sources:
        reason = "no_sources"
    elif joined is None:
        reason = "unknown_designation"
    elif not policy.permits(joined, channel):
        reason = "exceeds_ceiling"
    else:
        reason = "allowed"
    return Decision(channel, joined, reason == "allowed", reason)


def unknown_designations(
    corpus: CompiledCorpus, policy: DisclosurePolicy
) -> tuple[str, ...]:
    """Sorted IDs of records whose designation the policy does not declare."""
    return tuple(
        sorted(
            artifact.artifact_id
            for artifact in corpus.artifacts
            if policy.rank(artifact.designation) is None
        )
    )


def channel_view(
    corpus: CompiledCorpus, policy: DisclosurePolicy, channel: str
) -> CompiledCorpus:
    """The corpus restricted to records releasable on *channel*, before scoring."""
    if policy.ceiling(channel) is None:
        raise DisclosureError("unknown_channel", channel)
    unknown = unknown_designations(corpus, policy)
    if unknown:
        # An unlabelled record could be anything, so every view refuses.
        raise DisclosureError("unknown_designation", " ".join(unknown))
    releasable = tuple(
        artifact
        for artifact in corpus.artifacts
        if policy.permits(artifact.designation, channel)
    )
    permitted = frozenset(artifact.artifact_id for artifact in releasable)
    return CompiledCorpus(
        root=corpus.root,
        artifacts=releasable,
        chunks=tuple(chunk for chunk in corpus.chunks if chunk.artifact_id in permitted),
    )


def view_digest(view: CompiledCorpus) -> str:
    """Merkle root over exactly the records inside *view*."""
    return corpus_root_digest(view.artifacts)


def unpublishable_lines(
    corpus: CompiledCorpus, policy: DisclosurePolicy
) -> tuple[tuple[str, str], ...]:
    """Collapsed body lines of every record the publish channel may not carry.

    A heading counts twice: as its collapsed line and as its text without the
    markers. Blank lines and anything shorter than twenty characters after
    collapsing are skipped.
    """
    found: list[tuple[str, str]] = []
    for artifact in corpus.artifacts:
        if policy.permits(artifact.designation, PUBLISH_CHANNEL):
            continue
        lines = tuple(artifact.body.splitlines())
        headings = {index: title for index, _level, title in markdown_headings(lines)}
        for index, line in enumerate(lines):
            forms = [collapse_whitespace(line)]
            if index in headings:
                forms.append(collapse_whitespace(headings[index]))
            for text in forms:
                if len(text) >= _MIN_LINE_CHARS:
                    found.append((artifact.artifact_id, text))
    return tuple(found)
