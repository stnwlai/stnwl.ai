"""Evidence packets: exactly what one channel may receive for one question.

A packet is built over the channel view, so records above the channel's
ceiling are removed before any score is computed. Each entry carries a stable
handle (S1, S2, ... in rank order), the citation, the record's designation,
and the span text re-read and re-hashed from disk. Scores and the corpus root
stay out of the packet, so its canonical JSON digest depends only on the
question, the channel, the limit, the policy, and the releasable records.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .compiler import CompiledCorpus
from .disclosure import DisclosurePolicy, channel_view, view_digest
from .errors import AnswerError
from .hashing import canonical_json_bytes, sha256_bytes
from .models import EvidenceHit
from .retrieval import query_corpus, verify_citation

MAX_PACKET_LIMIT = 20


@dataclass(frozen=True, slots=True)
class PacketEntry:
    handle: str
    hit: EvidenceHit
    designation: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return self.hit.citation.to_dict() | {
            "designation": self.designation,
            "handle": self.handle,
            "heading": self.hit.heading,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class EvidencePacket:
    question: str
    channel: str
    limit: int
    policy: str
    view_root: str
    entries: tuple[PacketEntry, ...]

    def body(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "entries": [entry.to_dict() for entry in self.entries],
            "limit": self.limit,
            "policy": self.policy,
            "question": self.question,
            "schema_version": 1,
            "view_root": self.view_root,
        }

    @property
    def digest(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.body()))

    def to_dict(self) -> dict[str, Any]:
        return self.body() | {"digest": self.digest}

    def entry(self, handle: str) -> PacketEntry | None:
        return next((entry for entry in self.entries if entry.handle == handle), None)

    def covering(
        self, artifact_id: str, line_start: int, line_end: int
    ) -> PacketEntry | None:
        """The first entry, in rank order, whose span contains the line range."""
        return next(
            (
                entry
                for entry in self.entries
                if entry.hit.citation.artifact_id == artifact_id
                and entry.hit.citation.line_start <= line_start
                and line_end <= entry.hit.citation.line_end
            ),
            None,
        )


def build_packet(
    corpus: CompiledCorpus,
    policy: DisclosurePolicy,
    question: str,
    *,
    channel: str,
    limit: int,
) -> EvidencePacket:
    """Retrieve over the channel view and bind every span to verified bytes."""
    if not 1 <= limit <= MAX_PACKET_LIMIT:
        raise AnswerError(f"packet limit must be 1..{MAX_PACKET_LIMIT}")
    view = channel_view(corpus, policy, channel)
    hits = query_corpus(view, question, limit=limit)
    entries: list[PacketEntry] = []
    for rank, hit in enumerate(hits, start=1):
        artifact = view.artifact(hit.citation.artifact_id)
        # Guards retrieval that bypasses the view: every hit must be in it.
        if artifact is None:
            raise AnswerError("packet span is outside the channel view")
        entries.append(
            PacketEntry(
                handle=f"S{rank}",
                hit=hit,
                designation=artifact.designation,
                text=verify_citation(corpus.root, hit.citation),
            )
        )
    return EvidencePacket(
        question=question,
        channel=channel,
        limit=limit,
        policy=policy.digest,
        view_root=view_digest(view),
        entries=tuple(entries),
    )
