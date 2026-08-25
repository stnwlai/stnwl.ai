"""Transparent BM25 retrieval that returns verifiable evidence spans."""

from __future__ import annotations

import math
from collections import Counter
from pathlib import Path

from .compiler import CompiledCorpus
from .errors import CitationVerificationError, FrontMatterError
from .frontmatter import parse_document
from .hashing import sha256_bytes, sha256_file
from .models import Citation, EvidenceHit
from .text import normalize_excerpt, tokenize


def _inverse_document_frequency(document_count: int, document_frequency: int) -> float:
    return math.log(1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5))


def query_corpus(
    corpus: CompiledCorpus,
    query: str,
    *,
    limit: int = 8,
    k1: float = 1.35,
    b: float = 0.72,
) -> list[EvidenceHit]:
    """Rank chunks and expose every component of the resulting score."""
    query_terms = tokenize(query)
    if not query_terms or limit <= 0 or not corpus.chunks:
        return []
    unique_terms = tuple(dict.fromkeys(query_terms))
    term_sets = [set(chunk.terms) for chunk in corpus.chunks]
    document_frequency = {
        term: sum(1 for terms in term_sets if term in terms)
        for term in unique_terms
    }
    document_count = len(corpus.chunks)
    average_length = sum(len(chunk.terms) for chunk in corpus.chunks) / document_count
    hits: list[EvidenceHit] = []
    for chunk in corpus.chunks:
        frequencies = Counter(chunk.terms)
        bm25 = 0.0
        heading_boost = 0.0
        heading_terms = set(tokenize(chunk.heading))
        for term in unique_terms:
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            inverse_frequency = _inverse_document_frequency(
                document_count, document_frequency[term]
            )
            denominator = frequency + k1 * (
                1 - b + b * len(chunk.terms) / max(average_length, 1)
            )
            bm25 += inverse_frequency * (frequency * (k1 + 1)) / denominator
            if term in heading_terms:
                heading_boost += inverse_frequency * 0.35
        exact_phrase = 0.0
        normalized_query = " ".join(query_terms)
        if normalized_query and normalized_query in " ".join(chunk.terms):
            exact_phrase = 0.75
        score = bm25 + heading_boost + exact_phrase
        if score <= 0:
            continue
        citation = Citation(
            artifact_id=chunk.artifact_id,
            path=chunk.path,
            line_start=chunk.line_start,
            line_end=chunk.line_end,
            artifact_sha256=chunk.artifact_sha256,
            span_sha256=sha256_bytes(chunk.text.encode("utf-8")),
        )
        hits.append(
            EvidenceHit(
                citation=citation,
                heading=chunk.heading,
                excerpt=normalize_excerpt(chunk.text),
                score=score,
                score_breakdown={
                    "bm25": bm25,
                    "heading_boost": heading_boost,
                    "exact_phrase": exact_phrase,
                },
            )
        )
    return sorted(
        hits,
        key=lambda hit: (-hit.score, hit.citation.artifact_id, hit.citation.line_start),
    )[:limit]


def verify_citation(corpus_root: Path, citation: Citation) -> str:
    """Resolve a citation and prove both its artifact and line-span hashes."""
    root = corpus_root.resolve()
    path = (root / citation.path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise CitationVerificationError("citation path escapes corpus root") from exc
    if not path.is_file():
        raise CitationVerificationError(f"citation source is missing: {citation.path}")
    if sha256_file(path) != citation.artifact_sha256:
        raise CitationVerificationError(
            f"artifact digest changed for {citation.artifact_id}"
        )
    try:
        parsed = parse_document(path.read_text(encoding="utf-8"), source="citation")
    except (UnicodeDecodeError, FrontMatterError) as exc:
        raise CitationVerificationError("citation source is not canonical") from exc
    if parsed.metadata.get("id") != citation.artifact_id:
        raise CitationVerificationError("citation artifact id does not match its source")
    lines = parsed.lines
    if citation.line_start < 1 or citation.line_end < citation.line_start:
        raise CitationVerificationError("citation line range is invalid")
    if citation.line_end > len(lines):
        raise CitationVerificationError("citation line range exceeds the source")
    span = "\n".join(lines[citation.line_start - 1 : citation.line_end])
    if sha256_bytes(span.encode("utf-8")) != citation.span_sha256:
        raise CitationVerificationError(
            f"citation span changed for {citation.artifact_id}"
        )
    return span
