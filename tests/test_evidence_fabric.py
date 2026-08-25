from __future__ import annotations

import json
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

CORPUS_ROOT = REPO_ROOT / "hoss-stonewall" / "sample_corpus"


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
    def test_parses_supported_scalars_and_lists(self) -> None:
        parsed = parse_document(
            "---\nid: M0001\nactive: true\nweight: 1.5\ntags: [ALPHA, 'BETA']\n---\n\n# Record\n"
        )
        self.assertEqual(parsed.metadata["id"], "M0001")
        self.assertIs(parsed.metadata["active"], True)
        self.assertEqual(parsed.metadata["weight"], 1.5)
        self.assertEqual(parsed.metadata["tags"], ["ALPHA", "BETA"])

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

    def test_rejects_unterminated_lists(self) -> None:
        with self.assertRaisesRegex(FrontMatterError, "malformed list"):
            parse_document("---\ntags: [ALPHA, BETA\n---\n# Record\n")


class CompilerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = compile_corpus(CORPUS_ROOT)

    def test_compiles_reference_artifact_inventory(self) -> None:
        self.assertEqual(len(self.corpus.artifacts), 78)
        self.assertGreater(len(self.corpus.chunks), len(self.corpus.artifacts))

    def test_artifact_ids_are_unique(self) -> None:
        identifiers = [record.artifact_id for record in self.corpus.artifacts]
        self.assertEqual(len(identifiers), len(set(identifiers)))

    def test_chunk_addresses_are_unique(self) -> None:
        identifiers = [chunk.chunk_id for chunk in self.corpus.chunks]
        self.assertEqual(len(identifiers), len(set(identifiers)))

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
            self.assertEqual(attestation["artifact_count"], 78)

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

    def test_query_result_citation_verifies(self) -> None:
        hit = query_corpus(self.corpus, "discovery update", limit=1)[0]
        span = verify_citation(CORPUS_ROOT, hit.citation)
        self.assertTrue(span)

    def test_citation_rejects_relabelled_artifact_id(self) -> None:
        hit = query_corpus(self.corpus, "discovery update", limit=1)[0]
        relabelled = replace(hit.citation, artifact_id="Z9999")
        with self.assertRaisesRegex(CitationVerificationError, "artifact id"):
            verify_citation(CORPUS_ROOT, relabelled)

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

class PublishedMetricContractTests(unittest.TestCase):
    def test_portal_rows_use_coded_ids_and_declared_reference_source(self) -> None:
        data_root = REPO_ROOT / "docs" / "portal" / "data"
        payloads = {
            path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in data_root.glob("*.json")
        }
        for payload in payloads.values():
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["source_class"], "coded_reference")

        corpus = compile_corpus(CORPUS_ROOT)
        ids_by_type = {
            artifact_type: {
                record.artifact_id
                for record in corpus.artifacts
                if record.artifact_type == artifact_type
            }
            for artifact_type in {record.artifact_type for record in corpus.artifacts}
        }
        records_by_id = {record.artifact_id: record for record in corpus.artifacts}
        case_ids = ids_by_type["case"]
        for row in payloads["cases"]["matters"]:
            self.assertIn(row["id"], case_ids)
            self.assertTrue(row["label"].startswith(f"Matter {row['id']} —"))
        for row in payloads["cast"]["characters"]:
            self.assertIn(row["id"], ids_by_type["character"])
            self.assertNotIn("alias", row)
            self.assertNotIn("matters", row)
            self.assertEqual(row["records"], 1)
        for row in payloads["artifacts"]["artifacts"]:
            self.assertIn(row["id"], records_by_id)
            self.assertEqual(row["type"], records_by_id[row["id"]].artifact_type)
            self.assertEqual(row["date"], records_by_id[row["id"]].event_date)
            self.assertEqual(row["source"], "coded_reference")
            self.assertNotIn("matter", row)
        for row in payloads["deadlines"]["items"]:
            self.assertRegex(row["record"], r"^L\d{4}$")
            self.assertNotIn("matter", row)
        for row in payloads["billing"]["line_items"]:
            self.assertIn(row["record"], ids_by_type["billing"])
            self.assertNotIn("matter", row)

    def test_site_and_portal_metrics_match_compiled_reference(self) -> None:
        corpus = compile_corpus(CORPUS_ROOT)
        counts: dict[str, int] = {}
        for record in corpus.artifacts:
            counts[record.artifact_type] = counts.get(record.artifact_type, 0) + 1

        site = json.loads((REPO_ROOT / "docs" / "site-data.json").read_text(encoding="utf-8"))
        portal = json.loads(
            (REPO_ROOT / "docs" / "portal" / "data" / "metrics.json").read_text(
                encoding="utf-8"
            )
        )

        expected = {
            "artifacts": len(corpus.artifacts),
            "matters": counts["case"],
            "patterns": counts["pattern"],
            "roles": counts["character"],
            "emails": counts["email"],
            "classes": len(counts),
        }
        self.assertEqual(site["manifest"]["total_rows"], expected["artifacts"])
        self.assertEqual(site["cases"]["total_unique"], expected["matters"])
        self.assertEqual(site["patterns"]["total"], expected["patterns"])
        self.assertEqual(site["characters"]["total_unique"], expected["roles"])
        self.assertEqual(site["showcase_metrics"]["emails_processed"], expected["emails"])
        self.assertEqual(site["showcase_metrics"]["artifact_classes"], expected["classes"])
        self.assertEqual(site["evidence"]["chunks"], len(corpus.chunks))
        self.assertEqual(site["evidence"]["bundle_outputs"], len(BUNDLE_FILES))
        self.assertEqual(portal["cataloged_artifacts"], expected["artifacts"])
        self.assertEqual(portal["active_matters"], expected["matters"])
        self.assertEqual(portal["pattern_tags"], expected["patterns"])
        self.assertEqual(portal["role_records"], expected["roles"])
        self.assertEqual(portal["email_records"], expected["emails"])
        self.assertEqual(portal["artifact_classes"], expected["classes"])
        self.assertEqual(portal["bundle_outputs"], len(BUNDLE_FILES))


if __name__ == "__main__":
    unittest.main()
