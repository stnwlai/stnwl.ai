# Stonewall Official Brief

Stonewall is citation-first legal document intelligence: a product that helps
litigation teams find useful evidence while keeping the source and verification
trail attached to the result.

## Executive summary

Document systems often separate retrieval from proof. A search surface returns a
passage, while the user must reconstruct where it came from, why it ranked, and
whether it still matches the source. Stonewall treats those questions as one
product contract.

The corpus remains readable on disk. Derived catalogs and search indexes are
reproducible from that corpus. Retrieval results carry
line-addressed citations and transparent score components. Verification reopens
the source and checks both the artifact and cited span.

## Product claim

Evidence intelligence becomes more trustworthy when four properties reinforce
one another:

1. Inputs follow a strict and resolvable schema.
2. Derived surfaces are content-addressed and reproducible.
3. Retrieval returns explanations and citations together.
4. Publication requires an exact reviewed candidate tree.

The result is an evidence surface that can answer practical litigation questions
without turning provenance into a separate cleanup task.

## Engineering reference

The repository makes those four properties executable:

- The compiler rejects ambiguous front matter, duplicate IDs, and missing dates.
- The builder emits canonical catalog, index, and attestation files tied
  to a deterministic corpus root.
- The query layer reports BM25, heading, and exact-phrase score components with
  every cited span.
- The publication gate applies path, metadata, and content rules before requiring
  exact agreement with the committed tree manifest.

The implementation uses only the Python standard library and runs against the
checked-in coded corpus.

## Product value

The engineering contract supports a simple operating promise: move from a legal
question to a source-backed answer without losing the path between them.

That promise matters across recurring work such as chronology review, deposition
preparation, motion support, communication analysis, and matter handoff. A result
is more useful when the team can inspect its rank, open its source lines, and
verify later that the same citation still holds.

## Publication surfaces

The canonical product narrative lives at [stnwl.ai](https://www.stnwl.ai/). This
repository's Pages site presents the engineering exhibit, while the operator
portal shows how structured reference data can drive a static application
surface. The source repository provides the runnable proof behind both.

## Closing position

Stonewall makes provenance a first-class part of retrieval. The platform does
not merely return a plausible passage; it gives the passage an address, explains
its rank, and provides a deterministic way to check it again.
