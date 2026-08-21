import argparse
import contextlib
import io
import json
import os
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest import mock

from scripts.ingest_onedrive import (
    CaseRecord,
    IntakeError,
    build_case_keywords,
    choose_primary_case,
    classify_artifact,
    collect_input_files,
    cmd_ingest,
    cmd_sync_notion,
    derive_case_tag,
    extract_docx_text,
    load_manual_overrides,
    normalize_path_for_export,
    notion_api,
    score_case_matches,
)


class IngestOneDriveTests(unittest.TestCase):
    def test_extract_docx_text_reads_word_document_xml(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.docx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    """
                    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                      <w:body>
                        <w:p><w:r><w:t>First paragraph.</w:t></w:r></w:p>
                        <w:p><w:r><w:t>Second paragraph.</w:t></w:r></w:p>
                      </w:body>
                    </w:document>
                    """,
                )
            self.assertEqual(extract_docx_text(path), "First paragraph.\n\nSecond paragraph.")

    def test_case_matching_prefers_claim_number(self) -> None:
        case = CaseRecord(
            id="case-1",
            name="Smith v. Acme Corp",
            claim="CLAIM12345",
            plaintiff="John Smith",
            carrier_driver="Driver",
            legal_hold_status="Active Hold",
            date_of_loss="2024-11-05",
            date_of_complaint="2025-04-01",
            case_tag="Smith",
            keywords=build_case_keywords("Smith v. Acme Corp", "John Smith", "Driver", "Smith"),
            compact_claim="cl12345ab",
        )
        path = Path(r"C:\Users\<username>\OneDrive\Smith\CL12345AB claim file.pdf")
        candidates = score_case_matches(path, "Claim CL12345AB for Smith and Acme.", [case])
        primary = choose_primary_case(candidates)
        self.assertIsNotNone(primary)
        self.assertEqual(primary.case_name, "Smith v. Acme Corp")
        self.assertGreaterEqual(primary.score, 120)

    def test_classify_artifact_detects_billing(self) -> None:
        category, tags = classify_artifact(Path("Timesheet 2026-03-19 (timekeeper golden hours).csv"), "")
        self.assertEqual(category, "Billing Forensics")
        self.assertEqual(tags, ["billing", "forensics"])

    def test_classify_artifact_detects_operational_discovery_spreadsheet(self) -> None:
        category, tags = classify_artifact(Path("Driver - Delivery Records (rcvd 3.24.25).csv"), "")
        self.assertEqual(category, "Case Record")
        self.assertEqual(tags, ["discovery", "forensics"])

    def test_derive_case_tag_preserves_multi_plaintiff_name(self) -> None:
        self.assertEqual(derive_case_tag("Alpha/Beta v. Logistics Co"), "Alpha/Beta")

    def test_collect_input_files_applies_limit_after_global_sort(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_a = Path(tmpdir) / "a"
            root_b = Path(tmpdir) / "b"
            root_a.mkdir()
            root_b.mkdir()

            older = root_a / "older.txt"
            middle = root_a / "middle.txt"
            newest = root_b / "newest.txt"

            older.write_text("older", encoding="utf-8")
            middle.write_text("middle", encoding="utf-8")
            newest.write_text("newest", encoding="utf-8")

            os.utime(older, (100, 100))
            os.utime(middle, (200, 200))
            os.utime(newest, (300, 300))

            files = collect_input_files(
                [str(root_a), str(root_b)],
                root_mode="all",
                globs=None,
                extensions={".txt"},
                since_dt=None,
                limit=2,
            )

            self.assertEqual([path.name for path in files], ["newest.txt", "middle.txt"])

    def test_cmd_ingest_reprocesses_unchanged_file_when_manual_override_added(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_path = root / "general-note.txt"
            source_path.write_text("Generic note without a matter signal.", encoding="utf-8")

            case_index = root / "case_index.json"
            case_index.write_text(
                json.dumps(
                    [
                        {
                            "id": "case-1",
                            "name": "Smith v. Acme Corp",
                            "claim": "CLAIM12345",
                            "plaintiff": "John Smith",
                            "carrier_driver": "Driver",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            manifest = root / "manifest.jsonl"
            review_queue = root / "review_queue.md"
            derivative_root = root / "derivatives"
            manual_overrides = root / "manual_overrides.json"
            manual_overrides.write_text("[]", encoding="utf-8")

            args = argparse.Namespace(
                input=[str(source_path)],
                root="all",
                globs=None,
                since=None,
                limit=25,
                case_index=str(case_index),
                manifest=str(manifest),
                review_queue=str(review_queue),
                derivative_root=str(derivative_root),
                manual_overrides=str(manual_overrides),
                overwrite=False,
                extensions=None,
                dry_run=False,
                sync_notion=False,
            )

            self.assertEqual(cmd_ingest(args), 0)
            entries = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(entries[0]["case_match_status"], "unmatched")
            self.assertEqual(entries[0]["manual_override_mode"], "")

            manual_overrides.write_text(
                json.dumps(
                    [
                        {
                            "original_path": str(source_path.resolve()),
                            "mode": "link",
                            "case_name": "Smith v. Acme Corp",
                            "reason": "Operator confirmed the matter.",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            self.assertEqual(cmd_ingest(args), 0)
            entries = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(entries[0]["primary_case_name"], "Smith v. Acme Corp")
            self.assertEqual(entries[0]["case_match_status"], "linked")
            self.assertEqual(entries[0]["manual_override_mode"], "link")
            self.assertEqual(entries[0]["manual_override_reason"], "Operator confirmed the matter.")

    def test_normalize_path_for_export_strips_absolute_derivative(self) -> None:
        """normalize_path_for_export anchors at sources/ for derivative paths."""
        abs_path = r"C:\Users\<username>\Documents\Stonewall\sources\onedrive_ingest\firm\doc.pdf.md"
        self.assertEqual(
            normalize_path_for_export(abs_path, "firm"),
            "sources/onedrive_ingest/firm/doc.pdf.md",
        )

    def test_normalize_path_for_export_uses_source_root_for_original(self) -> None:
        """normalize_path_for_export falls back to source_root/filename for original paths."""
        abs_path = r"C:\Users\<username>\OneDrive - Your Firm\firm\doc.pdf"
        self.assertEqual(
            normalize_path_for_export(abs_path, "firm"),
            "firm/doc.pdf",
        )

    def test_normalize_path_for_export_passthrough_relative(self) -> None:
        """normalize_path_for_export leaves already-relative paths unchanged."""
        self.assertEqual(
            normalize_path_for_export("sources/onedrive_ingest/firm/doc.pdf.md"),
            "sources/onedrive_ingest/firm/doc.pdf.md",
        )

    def test_normalize_path_for_export_relative_with_source_root(self) -> None:
        """normalize_path_for_export ignores source_root when path is already repo-relative."""
        self.assertEqual(
            normalize_path_for_export("sources/onedrive_ingest/firm/doc.pdf.md", "firm"),
            "sources/onedrive_ingest/firm/doc.pdf.md",
        )

    @mock.patch("scripts.ingest_onedrive.urllib.request.urlopen", side_effect=urllib.error.URLError("proxy blocked"))
    def test_notion_api_wraps_url_error(self, mock_urlopen) -> None:
        with self.assertRaises(IntakeError) as ctx:
            notion_api("fake-token", "POST", "data_sources/demo/query", {})
        self.assertIn("Network error contacting Notion API", str(ctx.exception))


class SyncNotionTests(unittest.TestCase):
    """Tests for cmd_sync_notion worker clamping, dry-run, and error handling."""

    def _make_args(self, workers=1, dry_run=False, limit=100):
        return argparse.Namespace(
            manifest="/tmp/test_manifest.md",
            limit=limit,
            only_unsynced=True,
            dry_run=dry_run,
            workers=workers,
            dump_payload=None,
        )

    @mock.patch.dict("os.environ", {"NOTION_TOKEN": "fake-token"})
    @mock.patch("scripts.ingest_onedrive.time.sleep")
    @mock.patch("scripts.ingest_onedrive.fetch_archive_pages_by_file_path", return_value={})
    @mock.patch("scripts.ingest_onedrive.load_manifest", return_value=[
        {"title": "Test", "original_path": "test.md", "derivative_path": ""},
    ])
    @mock.patch("scripts.ingest_onedrive.build_archive_properties", return_value={})
    @mock.patch("scripts.ingest_onedrive.sync_archive_entry", return_value="page-id-1")
    @mock.patch("scripts.ingest_onedrive.write_manifest")
    def test_worker_clamping_zero_uses_single_worker(
        self, mock_write, mock_sync, mock_props, mock_load, mock_fetch, mock_sleep
    ) -> None:
        """Workers=0 is clamped to 1 and uses single-worker path."""
        args = self._make_args(workers=0)
        result = cmd_sync_notion(args)
        self.assertEqual(result, 0)
        mock_sync.assert_called_once()

    @mock.patch.dict("os.environ", {"NOTION_TOKEN": "fake-token"})
    @mock.patch("scripts.ingest_onedrive.time.sleep")
    @mock.patch("scripts.ingest_onedrive.time.monotonic", side_effect=[0.0, 0.0, 0.5])
    @mock.patch("scripts.ingest_onedrive.fetch_archive_pages_by_file_path", return_value={})
    @mock.patch("scripts.ingest_onedrive.load_manifest", return_value=[
        {"title": "Test", "original_path": "test.md", "derivative_path": ""},
    ])
    @mock.patch("scripts.ingest_onedrive.build_archive_properties", return_value={})
    @mock.patch("scripts.ingest_onedrive.sync_archive_entry", return_value="page-id-1")
    @mock.patch("scripts.ingest_onedrive.write_manifest")
    def test_worker_clamping_99_prints_adjustment(
        self, mock_write, mock_sync, mock_props, mock_load, mock_fetch, mock_mono, mock_sleep
    ) -> None:
        """Workers=99 is clamped to 16 and the adjustment message is printed."""
        buf = io.StringIO()
        args = self._make_args(workers=99)
        with contextlib.redirect_stdout(buf):
            cmd_sync_notion(args)
        self.assertIn("adjusted to supported range -> 16", buf.getvalue())

    @mock.patch.dict("os.environ", {"NOTION_TOKEN": "fake-token"})
    @mock.patch("scripts.ingest_onedrive.fetch_archive_pages_by_file_path", return_value={})
    @mock.patch("scripts.ingest_onedrive.load_manifest", return_value=[
        {"title": "Test", "original_path": "test.md", "derivative_path": ""},
    ])
    @mock.patch("scripts.ingest_onedrive.build_archive_properties", return_value={})
    @mock.patch("scripts.ingest_onedrive.sync_archive_entry")
    @mock.patch("scripts.ingest_onedrive.write_manifest")
    def test_dry_run_never_calls_sync_or_write(
        self, mock_write, mock_sync, mock_props, mock_load, mock_fetch
    ) -> None:
        """Dry-run must never call sync_archive_entry or write_manifest."""
        args = self._make_args(dry_run=True)
        result = cmd_sync_notion(args)
        self.assertEqual(result, 0)
        mock_sync.assert_not_called()
        mock_write.assert_not_called()
        mock_fetch.assert_not_called()

    @mock.patch.dict("os.environ", {}, clear=True)
    @mock.patch("scripts.ingest_onedrive.fetch_archive_pages_by_file_path")
    @mock.patch("scripts.ingest_onedrive.load_manifest", return_value=[
        {"title": "Test", "original_path": "test.md", "derivative_path": ""},
    ])
    @mock.patch("scripts.ingest_onedrive.build_archive_properties", return_value={})
    @mock.patch("scripts.ingest_onedrive.sync_archive_entry")
    @mock.patch("scripts.ingest_onedrive.write_manifest")
    def test_dry_run_without_token_is_allowed(
        self, mock_write, mock_sync, mock_props, mock_load, mock_fetch
    ) -> None:
        """Dry-run should work without NOTION_TOKEN for planning/reporting."""
        args = self._make_args(dry_run=True)
        result = cmd_sync_notion(args)
        self.assertEqual(result, 0)
        mock_fetch.assert_not_called()
        mock_sync.assert_not_called()
        mock_write.assert_not_called()

    @mock.patch.dict("os.environ", {"NOTION_TOKEN": "fake-token"})
    @mock.patch("scripts.ingest_onedrive.time.sleep")
    @mock.patch("scripts.ingest_onedrive.fetch_archive_pages_by_file_path", return_value={})
    @mock.patch("scripts.ingest_onedrive.load_manifest", return_value=[
        {"title": "Test", "original_path": "test.md", "derivative_path": ""},
    ])
    @mock.patch("scripts.ingest_onedrive.build_archive_properties", return_value={})
    @mock.patch("scripts.ingest_onedrive.sync_archive_entry", side_effect=RuntimeError("network down"))
    @mock.patch("scripts.ingest_onedrive.write_manifest")
    def test_runtime_error_caught_in_single_worker(
        self, mock_write, mock_sync, mock_props, mock_load, mock_fetch, mock_sleep
    ) -> None:
        """A RuntimeError (not IntakeError) must be caught, not abort the sync."""
        args = self._make_args(workers=1)
        result = cmd_sync_notion(args)
        self.assertEqual(result, 1)
        mock_write.assert_not_called()
        mock_sleep.assert_called()

    @mock.patch.dict("os.environ", {"NOTION_TOKEN": "fake-token"})
    @mock.patch("scripts.ingest_onedrive.time.sleep")
    @mock.patch("scripts.ingest_onedrive.time.monotonic", side_effect=[0.0, 0.0, 0.5])
    @mock.patch("scripts.ingest_onedrive.fetch_archive_pages_by_file_path", return_value={})
    @mock.patch("scripts.ingest_onedrive.load_manifest", return_value=[
        {"title": "Test", "original_path": "test.md", "derivative_path": ""},
    ])
    @mock.patch("scripts.ingest_onedrive.build_archive_properties", return_value={})
    @mock.patch("scripts.ingest_onedrive.sync_archive_entry", side_effect=RuntimeError("network down"))
    @mock.patch("scripts.ingest_onedrive.write_manifest")
    def test_runtime_error_caught_in_multi_worker(
        self, mock_write, mock_sync, mock_props, mock_load, mock_fetch, mock_mono, mock_sleep
    ) -> None:
        """A RuntimeError must be caught in the concurrent path too."""
        args = self._make_args(workers=2)
        result = cmd_sync_notion(args)
        self.assertEqual(result, 1)
        mock_write.assert_not_called()

    @mock.patch.dict("os.environ", {"NOTION_TOKEN": "fake-token"})
    @mock.patch("scripts.ingest_onedrive.time.sleep")
    @mock.patch("scripts.ingest_onedrive.fetch_archive_pages_by_file_path", return_value={})
    @mock.patch("scripts.ingest_onedrive.load_manifest", return_value=[
        {"title": "Test", "original_path": "test.md", "derivative_path": ""},
    ])
    @mock.patch("scripts.ingest_onedrive.build_archive_properties", return_value={})
    @mock.patch("scripts.ingest_onedrive.sync_archive_entry", return_value="page-id-1")
    @mock.patch("scripts.ingest_onedrive.write_manifest")
    def test_single_manifest_row_syncs_once_not_twice(
        self, mock_write, mock_sync, mock_props, mock_load, mock_fetch, mock_sleep
    ) -> None:
        """Regression: each manifest row should produce one sync operation."""
        args = self._make_args(workers=1)
        result = cmd_sync_notion(args)
        self.assertEqual(result, 0)
        mock_sync.assert_called_once()

    @mock.patch.dict("os.environ", {}, clear=True)
    @mock.patch("scripts.ingest_onedrive.load_manifest", return_value=[
        {"title": "Doc A", "original_path": "a.txt", "derivative_path": "a.md", "source_root": "firm"},
        {"title": "Doc B", "original_path": "b.txt", "derivative_path": "b.md", "source_root": "firm"},
    ])
    @mock.patch("scripts.ingest_onedrive.build_archive_properties", side_effect=[{"x": 1}, {"y": 2}])
    @mock.patch("scripts.ingest_onedrive.sync_archive_entry")
    @mock.patch("scripts.ingest_onedrive.write_manifest")
    def test_dump_payload_exits_without_live_sync(
        self, mock_write, mock_sync, mock_props, mock_load
    ) -> None:
        """--dump-payload + --dry-run writes the JSONL plan and returns 0 without live syncing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "payload.jsonl"
            args = self._make_args(dry_run=True, limit=2)
            args.dump_payload = str(out)
            result = cmd_sync_notion(args)
            self.assertEqual(result, 0)
            mock_sync.assert_not_called()
            mock_write.assert_not_called()

    @mock.patch.dict("os.environ", {}, clear=True)
    @mock.patch("scripts.ingest_onedrive.load_manifest", return_value=[
        {"title": "Doc A", "original_path": "a.txt", "derivative_path": "a.md"},
        {"title": "Doc B", "original_path": "b.txt", "derivative_path": "b.md"},
    ])
    @mock.patch("scripts.ingest_onedrive.build_archive_properties", side_effect=[{"x": 1}, {"y": 2}])
    def test_dump_payload_writes_sync_plan_in_dry_run(self, mock_props, mock_load) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "payload.jsonl"
            args = self._make_args(dry_run=True, limit=2)
            args.dump_payload = str(out)
            result = cmd_sync_notion(args)
            self.assertEqual(result, 0)
            rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["action"], "create")
            self.assertEqual(rows[0]["title"], "Doc A")

    @mock.patch.dict("os.environ", {}, clear=True)
    @mock.patch("scripts.ingest_onedrive.load_manifest", return_value=[
        {"title": "Doc A", "original_path": "a.txt", "derivative_path": "a.md", "notion_page_id": "abc-123"},
    ])
    @mock.patch("scripts.ingest_onedrive.build_archive_properties", return_value={"x": 1})
    def test_dump_payload_prefers_manifest_notion_page_id(self, mock_props, mock_load) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "payload.jsonl"
            args = self._make_args(dry_run=True, limit=1)
            args.only_unsynced = False
            args.dump_payload = str(out)
            result = cmd_sync_notion(args)
            self.assertEqual(result, 0)
            rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(rows[0]["action"], "update")
            self.assertEqual(rows[0]["existing_page_id"], "abc-123")

    @mock.patch.dict("os.environ", {"NOTION_TOKEN": "fake-token"})
    @mock.patch("scripts.ingest_onedrive.time.sleep")
    @mock.patch("scripts.ingest_onedrive.fetch_archive_pages_by_file_path", return_value={})
    @mock.patch("scripts.ingest_onedrive.load_manifest", return_value=[
        {
            "title": "Already Synced",
            "original_path": "test.md",
            "derivative_path": "sources/onedrive_ingest/firm/test.md",
            "notion_page_id": "existing-page-uuid",
            "source_root": "firm",
        },
    ])
    @mock.patch("scripts.ingest_onedrive.build_archive_properties", return_value={})
    @mock.patch("scripts.ingest_onedrive.sync_archive_entry", return_value="existing-page-uuid")
    @mock.patch("scripts.ingest_onedrive.write_manifest")
    def test_page_id_prefers_manifest_notion_page_id(
        self, mock_write, mock_sync, mock_props, mock_load, mock_fetch, mock_sleep
    ) -> None:
        """page_id must prefer entry['notion_page_id'] over existing lookup."""
        args = self._make_args(workers=1, limit=10)
        args.only_unsynced = False
        result = cmd_sync_notion(args)
        self.assertEqual(result, 0)
        call_args = mock_sync.call_args
        self.assertEqual(call_args[0][2], "existing-page-uuid")

    @mock.patch.dict("os.environ", {"NOTION_TOKEN": "fake-token"})
    @mock.patch("scripts.ingest_onedrive.time.sleep")
    @mock.patch("scripts.ingest_onedrive.fetch_archive_pages_by_file_path", return_value={})
    @mock.patch("scripts.ingest_onedrive.load_manifest", return_value=[
        {"title": "Doc A", "original_path": "a.txt", "derivative_path": "a.md"},
    ])
    @mock.patch("scripts.ingest_onedrive.build_archive_properties", return_value={"x": 1})
    @mock.patch("scripts.ingest_onedrive.sync_archive_entry", return_value="page-id-1")
    @mock.patch("scripts.ingest_onedrive.write_manifest")
    def test_dump_payload_does_not_disable_live_sync(
        self, mock_write, mock_sync, mock_props, mock_load, mock_fetch, mock_sleep
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "payload.jsonl"
            args = self._make_args(dry_run=False, limit=1)
            args.dump_payload = str(out)
            result = cmd_sync_notion(args)
            self.assertEqual(result, 0)
            self.assertTrue(out.exists())
            mock_sync.assert_called_once()

    @mock.patch("scripts.ingest_onedrive.time.sleep")
    @mock.patch("scripts.ingest_onedrive.urllib.request.urlopen", side_effect=urllib.error.URLError("proxy blocked"))
    def test_notion_api_retries_url_error(self, mock_urlopen, mock_sleep) -> None:
        with self.assertRaises(IntakeError):
            notion_api("fake-token", "POST", "data_sources/demo/query", {}, retries=3)
        self.assertEqual(mock_urlopen.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)


class LoadManualOverridesTests(unittest.TestCase):
    """Tests for the legacy manual overrides fallback (PR #105)."""

    def test_load_manual_overrides_falls_back_to_legacy_path(self) -> None:
        """When the local default file is missing but legacy exists, use legacy."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            local_path = root / "local_overrides.json"
            legacy_path = root / "legacy_overrides.json"

            source = (root / "some_doc.pdf").resolve()
            legacy_data = [
                {"original_path": str(source), "mode": "link", "reason": "Legacy."}
            ]
            legacy_path.write_text(json.dumps(legacy_data), encoding="utf-8")

            with (
                mock.patch("scripts.ingest_onedrive.DEFAULT_MANUAL_OVERRIDES", local_path),
                mock.patch("scripts.ingest_onedrive.LEGACY_MANUAL_OVERRIDES", legacy_path),
                contextlib.redirect_stderr(io.StringIO()) as stderr,
            ):
                overrides = load_manual_overrides(local_path)

            self.assertIn(str(source), overrides)
            self.assertEqual(overrides[str(source)]["mode"], "link")
            self.assertIn("falling back", stderr.getvalue())

    def test_load_manual_overrides_explicit_path_skips_legacy(self) -> None:
        """An explicit custom path should NOT read the legacy file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            custom_path = root / "custom.json"
            legacy_path = root / "legacy_overrides.json"

            custom_path.write_text("[]", encoding="utf-8")
            legacy_path.write_text(
                json.dumps([{"original_path": "/x", "mode": "no_case", "reason": "x"}]),
                encoding="utf-8",
            )

            with (
                mock.patch("scripts.ingest_onedrive.DEFAULT_MANUAL_OVERRIDES", root / "default.json"),
                mock.patch("scripts.ingest_onedrive.LEGACY_MANUAL_OVERRIDES", legacy_path),
            ):
                overrides = load_manual_overrides(custom_path)

            self.assertEqual(overrides, {})

    def test_load_manual_overrides_merges_legacy_without_overwriting_local(self) -> None:
        """When both local and legacy exist, local entries take precedence and
        legacy-only entries are carried through."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            local_path = root / "local_overrides.json"
            legacy_path = root / "legacy_overrides.json"

            shared_source = (root / "shared.pdf").resolve()
            legacy_only_source = (root / "legacy_only.txt").resolve()

            local_data = [
                {"original_path": str(shared_source), "mode": "link", "reason": "Local wins."}
            ]
            legacy_data = [
                {"original_path": str(shared_source), "mode": "no_case", "reason": "Legacy."},
                {"original_path": str(legacy_only_source), "mode": "no_case", "reason": "Legacy only."},
            ]

            local_path.write_text(json.dumps(local_data), encoding="utf-8")
            legacy_path.write_text(json.dumps(legacy_data), encoding="utf-8")

            with (
                mock.patch("scripts.ingest_onedrive.DEFAULT_MANUAL_OVERRIDES", local_path),
                mock.patch("scripts.ingest_onedrive.LEGACY_MANUAL_OVERRIDES", legacy_path),
            ):
                overrides = load_manual_overrides(local_path)

            # Local wins for shared key
            self.assertEqual(overrides[str(shared_source)]["mode"], "link")
            self.assertEqual(overrides[str(shared_source)]["reason"], "Local wins.")
            # Legacy-only key is carried through
            self.assertIn(str(legacy_only_source), overrides)
            self.assertEqual(overrides[str(legacy_only_source)]["mode"], "no_case")


if __name__ == "__main__":
    unittest.main()
