from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from stonewall.bundle import BUNDLE_FILES, build_bundle, bundle_bytes, verify_bundle
from stonewall.compiler import compile_corpus
from stonewall.errors import (
    CitationVerificationError,
    CorpusValidationError,
    FrontMatterError,
)
from stonewall.frontmatter import parse_document
from stonewall.hashing import merkle_root
from stonewall.retrieval import query_corpus, verify_citation

CORPUS_ROOT = REPO_ROOT / "examples" / "corpus"


def artifact(
    artifact_id: str,
    artifact_type: str,
    *,
    body: str = "# Evidence\n\nA source-grounded evidence paragraph.",
) -> str:
    fields = [
        f"id: {artifact_id}",
        f"type: {artifact_type}",
        "date: 2025-01-01",
    ]
    return "---\n" + "\n".join(fields) + "\n---\n\n" + body + "\n"


class FrontMatterTests(unittest.TestCase):
    def test_parses_string_values_and_matching_quotes(self) -> None:
        parsed = parse_document(
            "---\nid: M0001\ntype: case\ndate: '2025-01-01'\n---\n\n# Record\n"
        )
        self.assertEqual(parsed.metadata["id"], "M0001")
        self.assertEqual(parsed.metadata["type"], "case")
        self.assertEqual(parsed.metadata["date"], "2025-01-01")

    def test_retains_original_body_line_address(self) -> None:
        parsed = parse_document("---\nid: M0001\ntype: case\n---\n\n# Record\n\nBody\n")
        self.assertEqual(parsed.body_start_line, 6)
        self.assertEqual(parsed.lines[5], "# Record")

    def test_rejects_duplicate_keys(self) -> None:
        with self.assertRaisesRegex(FrontMatterError, "duplicate key"):
            parse_document("---\nid: M0001\nid: M0002\n---\n# Record\n")

    def test_rejects_noncanonical_keys(self) -> None:
        with self.assertRaisesRegex(FrontMatterError, "invalid key"):
            parse_document("---\nBad-Key: value\n---\n# Record\n")

    def test_rejects_crlf_sources(self) -> None:
        with self.assertRaisesRegex(FrontMatterError, "LF line separators"):
            parse_document("---\r\nid: M0001\r\n---\r\n# Record\r\n")

    def test_rejects_unicode_line_separators(self) -> None:
        with self.assertRaisesRegex(FrontMatterError, "LF line separators"):
            parse_document("---\nid: M0001\n---\n# Record\u2028Body\n")

    def test_rejects_malformed_quoted_values(self) -> None:
        with self.assertRaisesRegex(FrontMatterError, "malformed quoted"):
            parse_document("---\nid: 'M0001\n---\n# Record\n")


class CompilerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = compile_corpus(CORPUS_ROOT)

    def test_compiles_reference_artifact_inventory(self) -> None:
        self.assertEqual(len(self.corpus.artifacts), 6)
        self.assertGreater(len(self.corpus.chunks), len(self.corpus.artifacts))

    def test_artifact_ids_are_unique(self) -> None:
        identifiers = [record.artifact_id for record in self.corpus.artifacts]
        self.assertEqual(len(identifiers), len(set(identifiers)))

    def test_chunk_addresses_are_unique(self) -> None:
        identifiers = [chunk.chunk_id for chunk in self.corpus.chunks]
        self.assertEqual(len(identifiers), len(set(identifiers)))

    def test_heading_chunks_do_not_duplicate_heading_terms(self) -> None:
        chunk = next(
            item
            for item in self.corpus.chunks
            if item.artifact_id == "D0001" and item.text == "# Deposition Scheduling Note"
        )
        self.assertEqual(chunk.terms, ("deposition", "scheduling", "note"))

    def test_rejects_duplicate_artifact_ids(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "one.md").write_text(artifact("M0001", "case"), encoding="utf-8")
            (root / "two.md").write_text(artifact("M0001", "case"), encoding="utf-8")
            with self.assertRaisesRegex(CorpusValidationError, "duplicate artifact id"):
                compile_corpus(root)

    def test_rejects_missing_date(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "record.md").write_text(
                "---\nid: E0001\ntype: email\n---\n\n# Evidence\n\nRecord.\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(CorpusValidationError, "missing required field"):
                compile_corpus(root)

    def test_rejects_non_calendar_date(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "record.md").write_text(
                artifact("E0001", "email").replace("2025-01-01", "2025-02-30"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(CorpusValidationError, "calendar date"):
                compile_corpus(root)

    def test_rejects_multiple_h1_titles(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "record.md").write_text(
                artifact("E0001", "email", body="# First\n\n# Second"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(CorpusValidationError, "exactly one H1"):
                compile_corpus(root)

    def test_fenced_h1_does_not_count_as_document_title(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "record.md").write_text(
                artifact("E0001", "email", body="```markdown\n# Hidden\n```\n\nBody."),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(CorpusValidationError, "exactly one H1"):
                compile_corpus(root)

    def test_rejects_symlinked_corpus_source(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "record.txt"
            target.write_text(artifact("E0001", "email"), encoding="utf-8")
            try:
                (root / "record.md").symlink_to(target.name)
            except OSError as exc:  # pragma: no cover - platform policy
                self.skipTest(f"symlinks unavailable: {exc}")
            with self.assertRaisesRegex(CorpusValidationError, "symlinks"):
                compile_corpus(root)

    def test_rejects_output_inside_corpus(self) -> None:
        with self.assertRaisesRegex(CorpusValidationError, "inside the corpus"):
            build_bundle(CORPUS_ROOT, CORPUS_ROOT / "generated")


class ReproducibleBundleTests(unittest.TestCase):
    def test_independent_builds_are_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            left = root / "left"
            right = root / "right"
            build_bundle(CORPUS_ROOT, left)
            build_bundle(CORPUS_ROOT, right)
            self.assertEqual(bundle_bytes(left), bundle_bytes(right))

    def test_bundle_contains_only_owned_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "bundle"
            build_bundle(CORPUS_ROOT, output)
            self.assertEqual(set(bundle_bytes(output)), set(BUNDLE_FILES))

    def test_bundle_reader_rejects_unexpected_directory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "bundle"
            build_bundle(CORPUS_ROOT, output)
            (output / "unexpected").mkdir()
            with self.assertRaisesRegex(CorpusValidationError, "unexpected"):
                bundle_bytes(output)

    def test_build_preflights_non_regular_expected_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "bundle"
            build_bundle(CORPUS_ROOT, output)
            catalog_before = (output / "catalog.json").read_bytes()
            (output / "search-index.json").unlink()
            (output / "search-index.json").mkdir()
            with self.assertRaisesRegex(CorpusValidationError, "non-regular"):
                build_bundle(CORPUS_ROOT, output)
            self.assertEqual((output / "catalog.json").read_bytes(), catalog_before)

    def test_attestation_binds_each_generated_surface(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "bundle"
            attestation = build_bundle(CORPUS_ROOT, output)
            self.assertEqual(set(attestation["outputs"]), set(BUNDLE_FILES) - {"attestation.json"})
            self.assertEqual(attestation["artifact_count"], 6)

    def test_verify_bundle_detects_byte_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "bundle"
            build_bundle(CORPUS_ROOT, output)
            with (output / "catalog.json").open("ab") as handle:
                handle.write(b" ")
            with self.assertRaisesRegex(CorpusValidationError, "not reproducible"):
                verify_bundle(CORPUS_ROOT, output)

    def test_build_refuses_unowned_output_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "bundle"
            output.mkdir()
            (output / "operator-note.txt").write_text("retain", encoding="utf-8")
            with self.assertRaisesRegex(CorpusValidationError, "unowned output"):
                build_bundle(CORPUS_ROOT, output)

    def test_merkle_root_is_input_order_independent(self) -> None:
        leaves = [("b.md", "b" * 64), ("a.md", "a" * 64)]
        self.assertEqual(merkle_root(leaves), merkle_root(reversed(leaves)))

    def test_merkle_root_changes_with_one_leaf(self) -> None:
        baseline = merkle_root([("a.md", "a" * 64)])
        changed = merkle_root([("a.md", "b" * 64)])
        self.assertNotEqual(baseline, changed)


class RetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = compile_corpus(CORPUS_ROOT)

    def test_query_returns_explainable_scores(self) -> None:
        hits = query_corpus(self.corpus, "deposition scheduling", limit=3)
        self.assertEqual(len(hits), 3)
        self.assertGreater(hits[0].score_breakdown["bm25"], 0)
        self.assertIn("heading_boost", hits[0].score_breakdown)

    def test_exact_phrase_does_not_cross_heading_and_source(self) -> None:
        hits = query_corpus(self.corpus, "schedule the witness", limit=30)
        body_hit = next(
            hit
            for hit in hits
            if hit.citation.artifact_id == "D0001" and hit.citation.line_start == 11
        )
        self.assertEqual(body_hit.score_breakdown["exact_phrase"], 0.0)

    def test_exact_phrase_matches_source_span(self) -> None:
        hits = query_corpus(self.corpus, "witness scheduling", limit=30)
        source_hit = next(
            hit
            for hit in hits
            if hit.citation.artifact_id == "E0001" and hit.citation.line_start == 11
        )
        self.assertEqual(source_hit.score_breakdown["exact_phrase"], 0.75)

    def test_query_result_citation_verifies(self) -> None:
        hit = query_corpus(self.corpus, "discovery update", limit=1)[0]
        span = verify_citation(CORPUS_ROOT, hit.citation)
        self.assertTrue(span)

    def test_citation_rejects_relabelled_artifact_id(self) -> None:
        hit = query_corpus(self.corpus, "discovery update", limit=1)[0]
        relabelled = replace(hit.citation, artifact_id="Z9999")
        with self.assertRaisesRegex(CitationVerificationError, "artifact id"):
            verify_citation(CORPUS_ROOT, relabelled)

    def test_citation_rejects_tampered_span_digest(self) -> None:
        hit = query_corpus(self.corpus, "discovery update", limit=1)[0]
        tampered = replace(hit.citation, span_sha256="0" * 64)
        with self.assertRaisesRegex(CitationVerificationError, "span changed"):
            verify_citation(CORPUS_ROOT, tampered)

    def test_citation_detects_artifact_mutation(self) -> None:
        hit = query_corpus(self.corpus, "discovery update", limit=1)[0]
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            destination = root / hit.citation.path
            destination.parent.mkdir(parents=True)
            source = CORPUS_ROOT / hit.citation.path
            destination.write_text(source.read_text(encoding="utf-8") + "drift\n", encoding="utf-8")
            with self.assertRaisesRegex(CitationVerificationError, "digest changed"):
                verify_citation(root, hit.citation)

    def test_empty_query_returns_no_hits(self) -> None:
        self.assertEqual(query_corpus(self.corpus, "---", limit=5), [])


if __name__ == "__main__":
    unittest.main()
