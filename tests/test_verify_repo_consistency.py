import tempfile
import unittest
from pathlib import Path

from scripts.verify_repo_consistency import (
    build_report,
    extract_repo_path,
    has_blocking_issues,
)


class VerifyRepoConsistencyTests(unittest.TestCase):
    def test_extract_repo_path_prefers_repo_segment(self) -> None:
        self.assertEqual(
            extract_repo_path("OneDrive + sources/transcripts/Smith - Call with OC 3.19.26.txt"),
            "sources/transcripts/Smith - Call with OC 3.19.26.txt",
        )
        self.assertIsNone(extract_repo_path("OneDrive/Only/external/file.docx"))

    def test_build_report_flags_missing_manifest_paths_and_uncataloged_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            (repo_root / "catalog").mkdir()
            (repo_root / "sources" / "analysis").mkdir(parents=True)
            (repo_root / "sources" / "transcripts").mkdir(parents=True)
            (repo_root / "sources" / "variants" / "transcripts").mkdir(parents=True)
            (repo_root / "sources" / "depositions").mkdir(parents=True)
            (repo_root / "sources" / "skills").mkdir(parents=True)

            manifest_path = repo_root / "catalog" / "manifest.md"
            manifest_path.write_text(
                "\n".join(
                    [
                        "# Manifest",
                        "",
                        "| ID | File | Type | Date | Characters | Patterns | Case | Summary | Analyzed |",
                        "|----|------|------|------|------------|----------|------|---------|----------|",
                        "| A001 | sources/analysis/canonical.pdf | other | 2026-03-19 | — | — | — | canonical pdf | no |",
                        "| A002 | OneDrive + sources/transcripts/call.txt | transcript | 2026-03-19 | — | — | — | call txt | no |",
                        "| A003 | sources/variants/transcripts/call.docx | transcript | 2026-03-19 | — | — | — | call docx | no |",
                        "| A004 | sources/transcripts/missing.txt | transcript | 2026-03-19 | — | — | — | missing path | no |",
                    ]
                ),
                encoding="utf-8",
            )

            (repo_root / "sources" / "analysis" / "canonical.pdf").write_bytes(b"%PDF-1.4 canonical")
            (repo_root / "sources" / "analysis" / "canonical.pdf.md").write_text(
                "sidecar", encoding="utf-8"
            )
            (repo_root / "sources" / "analysis" / "no_sidecar.pdf").write_bytes(b"%PDF-1.4 uncataloged")
            (repo_root / "sources" / "transcripts" / "call.txt").write_text(
                "call transcript", encoding="utf-8"
            )
            (repo_root / "sources" / "transcripts" / "call.md").write_text(
                "call transcript markdown", encoding="utf-8"
            )
            (repo_root / "sources" / "transcripts" / "uncataloged.txt").write_text(
                "needs manifest row", encoding="utf-8"
            )
            (repo_root / "sources" / "variants" / "transcripts" / "call.docx").write_text(
                "same call in docx", encoding="utf-8"
            )
            (repo_root / "sources" / "depositions" / "Sample_Deposition_Verbatim.md").write_text(
                "indexed elsewhere", encoding="utf-8"
            )
            (repo_root / "sources" / "skills" / "qed_helper.mjs").write_text(
                "export const x = 1;", encoding="utf-8"
            )

            report = build_report(repo_root=repo_root, manifest_path=manifest_path)

            self.assertEqual(report["tracked_source_file_count"], 6)
            self.assertEqual(
                report["manifest_missing_paths"],
                [
                    {
                        "id": "A004",
                        "file_field": "sources/transcripts/missing.txt",
                        "repo_path": "sources/transcripts/missing.txt",
                    }
                ],
            )
            self.assertEqual(
                sorted(report["uncataloged_canonical_sources"]),
                [
                    "sources/analysis/no_sidecar.pdf",
                    "sources/transcripts/uncataloged.txt",
                ],
            )
            self.assertEqual(report["uncataloged_variant_sources"], [])
            self.assertEqual(report["pdf_missing_markdown"], ["sources/analysis/no_sidecar.pdf"])
            self.assertEqual(
                report["variant_clusters"],
                [
                    {
                        "normalized_stem": "call",
                        "canonical_paths": [
                            "sources/transcripts/call.md",
                            "sources/transcripts/call.txt",
                        ],
                        "variant_paths": ["sources/variants/transcripts/call.docx"],
                    }
                ],
            )
            self.assertEqual(report["unresolved_duplicate_name_clusters"], [])
            self.assertEqual(report["exact_duplicate_canonical_conflicts"], [])
            self.assertEqual(report["exact_duplicate_variant_groups"], [])
            self.assertTrue(has_blocking_issues(report))

    def test_has_blocking_issues_false_for_clean_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            (repo_root / "catalog").mkdir()
            (repo_root / "sources" / "analysis").mkdir(parents=True)

            manifest_path = repo_root / "catalog" / "manifest.md"
            manifest_path.write_text(
                "\n".join(
                    [
                        "# Manifest",
                        "",
                        "| ID | File | Type | Date | Characters | Patterns | Case | Summary | Analyzed |",
                        "|----|------|------|------|------------|----------|------|---------|----------|",
                        "| A001 | sources/analysis/canonical.pdf | other | 2026-03-19 | - | - | - | canonical pdf | no |",
                    ]
                ),
                encoding="utf-8",
            )

            (repo_root / "sources" / "analysis" / "canonical.pdf").write_bytes(b"%PDF-1.4 canonical")
            (repo_root / "sources" / "analysis" / "canonical.pdf.md").write_text(
                "sidecar", encoding="utf-8"
            )

            report = build_report(repo_root=repo_root, manifest_path=manifest_path)
            self.assertFalse(has_blocking_issues(report))

    def test_build_report_ignores_non_catalog_a_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            (repo_root / "catalog").mkdir()
            (repo_root / "sources" / "analysis").mkdir(parents=True)

            manifest_path = repo_root / "catalog" / "manifest.md"
            manifest_path.write_text(
                "\n".join(
                    [
                        "# Manifest",
                        "",
                        "| ID | File | Type | Date | Characters | Patterns | Case | Summary | Analyzed |",
                        "|----|------|------|------|------------|----------|------|---------|----------|",
                        "| A001 | sources/analysis/canonical.pdf | other | 2026-03-19 | - | - | - | canonical pdf | no |",
                        "",
                        "## Historical Snapshot",
                        "| ID | File | Possible Primary |",
                        "|----|------|------------------|",
                        "| A001 | sources/analysis/canonical.pdf | original |",
                    ]
                ),
                encoding="utf-8",
            )

            (repo_root / "sources" / "analysis" / "canonical.pdf").write_bytes(b"%PDF-1.4 canonical")
            (repo_root / "sources" / "analysis" / "canonical.pdf.md").write_text(
                "sidecar", encoding="utf-8"
            )

            report = build_report(repo_root=repo_root, manifest_path=manifest_path)
            self.assertEqual(report["manifest_row_count"], 1)

    def test_build_report_ignores_separately_indexed_subtrees(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            (repo_root / "catalog").mkdir()
            (repo_root / "sources" / "depositions").mkdir(parents=True)

            manifest_path = repo_root / "catalog" / "manifest.md"
            manifest_path.write_text("# Manifest\n", encoding="utf-8")

            (repo_root / "sources" / "depositions" / "Sample_Deposition_Verbatim.md").write_text(
                "indexed elsewhere", encoding="utf-8"
            )
            report = build_report(repo_root=repo_root, manifest_path=manifest_path)
            self.assertEqual(report["tracked_source_file_count"], 0)
            self.assertEqual(report["uncataloged_canonical_sources"], [])

    def test_variant_exact_duplicates_are_not_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            (repo_root / "catalog").mkdir()
            (repo_root / "sources" / "transcripts").mkdir(parents=True)
            (repo_root / "sources" / "variants" / "transcripts").mkdir(parents=True)

            manifest_path = repo_root / "catalog" / "manifest.md"
            manifest_path.write_text(
                "\n".join(
                    [
                        "# Manifest",
                        "",
                        "| ID | File | Type | Date | Characters | Patterns | Case | Summary | Analyzed |",
                        "|----|------|------|------|------------|----------|------|---------|----------|",
                        "| A001 | sources/transcripts/call.txt | transcript | 2026-03-19 | - | - | - | canonical call | no |",
                    ]
                ),
                encoding="utf-8",
            )

            (repo_root / "sources" / "transcripts" / "call.txt").write_text(
                "same bytes", encoding="utf-8"
            )
            (repo_root / "sources" / "variants" / "transcripts" / "call.txt").write_text(
                "same bytes", encoding="utf-8"
            )

            report = build_report(repo_root=repo_root, manifest_path=manifest_path)
            self.assertEqual(report["exact_duplicate_canonical_conflicts"], [])
            self.assertEqual(len(report["exact_duplicate_variant_groups"]), 1)
            self.assertFalse(has_blocking_issues(report))

    def test_build_report_normalizes_period_and_underscore_families(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            (repo_root / "catalog").mkdir()
            (repo_root / "sources" / "analysis").mkdir(parents=True)

            manifest_path = repo_root / "catalog" / "manifest.md"
            manifest_path.write_text(
                "\n".join(
                    [
                        "# Manifest",
                        "",
                        "| ID | File | Type | Date | Characters | Patterns | Case | Summary | Analyzed |",
                        "|----|------|------|------|------------|----------|------|---------|----------|",
                        "| A001 | sources/analysis/Fleet Notes 3.16.26.docx | other | 2026-03-16 | - | - | - | notes docx | no |",
                    ]
                ),
                encoding="utf-8",
            )

            (repo_root / "sources" / "analysis" / "Fleet Notes 3.16.26.docx").write_text(
                "docx placeholder", encoding="utf-8"
            )
            (repo_root / "sources" / "analysis" / "Fleet_Notes_3_16_26.md").write_text(
                "markdown companion", encoding="utf-8"
            )

            report = build_report(repo_root=repo_root, manifest_path=manifest_path)
            self.assertEqual(report["uncataloged_canonical_sources"], [])

    def test_build_report_ignores_generated_underscore_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            (repo_root / "catalog").mkdir()
            (repo_root / "sources" / "transcripts").mkdir(parents=True)

            manifest_path = repo_root / "catalog" / "manifest.md"
            manifest_path.write_text("# Manifest\n", encoding="utf-8")

            (repo_root / "sources" / "transcripts" / "call_pdf.md").write_text(
                "generated sidecar", encoding="utf-8"
            )

            report = build_report(repo_root=repo_root, manifest_path=manifest_path)
            self.assertEqual(report["tracked_source_file_count"], 0)


if __name__ == "__main__":
    unittest.main()
