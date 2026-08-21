"""Unit tests for scripts/docs_drift_watcher.py.

Stdlib only. No network calls — the GitHub client is monkeypatched.
"""

from __future__ import annotations

import json
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import docs_drift_watcher as dd  # noqa: E402


class ExtractPythonSymbolsTest(unittest.TestCase):
    def test_picks_up_public_functions_and_classes(self) -> None:
        code = textwrap.dedent(
            """
            def ingest_corpus(path):
                return path

            async def stream_pages():
                yield 1

            class CorpusPipeline:
                pass

            def _private():
                pass
            """
        )
        out = set(dd.extract_python_symbols(code))
        self.assertIn(("ingest_corpus", "function"), out)
        self.assertIn(("stream_pages", "function"), out)
        self.assertIn(("CorpusPipeline", "class"), out)
        self.assertNotIn(("_private", "function"), out)

    def test_unparseable_diff_falls_back_to_regex(self) -> None:
        body = "def renamed_handler(arg):\n    # missing block tail\n"
        out = set(dd._python_regex_fallback(body))
        self.assertIn(("renamed_handler", "function"), out)


class ExtractJsSymbolsTest(unittest.TestCase):
    def test_export_forms(self) -> None:
        code = textwrap.dedent(
            """
            export function buildTracker() {}
            export const TRACKER_VERSION = 4;
            export class TrackerHelper {}
            function localHelper() {}
            class privateThing {}
            """
        )
        out = dict(dd.extract_js_symbols(code))
        self.assertEqual(out.get("buildTracker"), "export")
        self.assertEqual(out.get("TRACKER_VERSION"), "export")
        self.assertEqual(out.get("TrackerHelper"), "export")
        self.assertEqual(out.get("localHelper"), "function")
        # lowercase-class is filtered by the regex
        self.assertNotIn("privateThing", out)


class ExtractRoutesTest(unittest.TestCase):
    def test_route_patterns(self) -> None:
        code = textwrap.dedent(
            """
            @app.route('/v1/matters')
            def matters(): pass

            app.get("/v2/cases/:id")
            router.post('/internal/sync')
            """
        )
        routes = {p for p, _ in dd.extract_routes(code)}
        self.assertEqual(
            routes,
            {"/v1/matters", "/v2/cases/:id", "/internal/sync"},
        )


class ExtractFromPatchTest(unittest.TestCase):
    def test_rename_appears_on_both_sides(self) -> None:
        patch = (
            "@@ -1,3 +1,3 @@\n"
            "-def IngestPipeline():\n"
            "+def CorpusPipeline():\n"
            "     return 1\n"
        )
        names = {n for n, _ in dd.extract_from_patch("scripts/x.py", patch)}
        # The diff fragments alone are unparseable, but the regex fallback
        # still picks up both names.
        self.assertTrue(
            {"IngestPipeline", "CorpusPipeline"}.issubset(names),
            f"expected both names in {names}",
        )

    def test_empty_patch_returns_nothing(self) -> None:
        self.assertEqual(dd.extract_from_patch("x.py", None), [])
        self.assertEqual(dd.extract_from_patch("x.py", ""), [])


class ScanDocTest(unittest.TestCase):
    def test_word_boundary_match_and_excerpt(self) -> None:
        sym = dd.Symbol(
            name="CorpusPipeline",
            kind="class",
            source_file="scripts/pipeline.py",
            pr_number=482,
            pr_title="Rename pipeline",
            pr_url="https://example.test/482",
        )
        with self._tmp() as tmp:
            doc = tmp / "page.md"
            doc.write_text(
                "intro line\n"
                "Use `CorpusPipeline` to begin.\n"
                "CorpusPipelineXYZ should NOT match.\n",
                encoding="utf-8",
            )
            hits = dd.scan_doc(doc, {"CorpusPipeline": sym})
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].line_number, 2)
        self.assertIn("CorpusPipeline", hits[0].excerpt)

    def test_route_symbols_match_without_word_boundaries(self) -> None:
        sym = dd.Symbol(
            name="/v1/matters",
            kind="route",
            source_file="api/routes.py",
            pr_number=9,
            pr_title="Route change",
            pr_url="https://example.test/9",
        )
        with self._tmp() as tmp:
            doc = tmp / "routes.md"
            doc.write_text(
                "Call GET /v1/matters for the list.\n"
                "See v1/matters without a leading slash here.\n",
                encoding="utf-8",
            )
            hits = dd.scan_doc(doc, {"/v1/matters": sym})
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].line_number, 1)

    def _tmp(self):
        import tempfile, contextlib

        @contextlib.contextmanager
        def _ctx():
            with tempfile.TemporaryDirectory() as d:
                yield Path(d)

        return _ctx()


class BannerTest(unittest.TestCase):
    def test_banner_inserts_after_yaml_frontmatter(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            doc = Path(d) / "page.md"
            doc.write_text(
                "---\ntitle: API\n---\n\n# Body\n",
                encoding="utf-8",
            )
            sym = dd.Symbol(
                name="ingest_corpus",
                kind="function",
                source_file="scripts/x.py",
                pr_number=3,
                pr_title="Refactor",
                pr_url="u",
            )
            hits = [dd.DocHit(str(doc), sym, 3, "# Body")]
            banner = dd.render_banner(hits, "2026-05-21T13:17:00Z")
            dd.apply_banner(doc, banner)
            text = doc.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\ntitle: API\n---\n\n"))
            self.assertIn(dd.BANNER_BEGIN, text)
            self.assertLess(text.index("---"), text.index(dd.BANNER_BEGIN))

    def test_banner_blockquote_prefixes_continuation_lines(self) -> None:
        sym = dd.Symbol(
            name="ingest_corpus",
            kind="function",
            source_file="scripts/x.py",
            pr_number=12,
            pr_title="Refactor",
            pr_url="u",
        )
        banner = dd.render_banner(
            [dd.DocHit("docs/x.md", sym, 1, "line")],
            "2026-05-21T13:17:00Z",
        )
        for line in banner.splitlines():
            if line.strip().startswith("symbols:"):
                self.assertTrue(
                    line.startswith("> "),
                    f"continuation line missing blockquote: {line!r}",
                )

    def test_banner_round_trip_is_idempotent(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            doc = Path(d) / "page.md"
            doc.write_text("# Page\n\nbody.\n", encoding="utf-8")
            sym = dd.Symbol(
                name="ingest_corpus",
                kind="function",
                source_file="scripts/x.py",
                pr_number=12,
                pr_title="Refactor",
                pr_url="u",
            )
            hits = [dd.DocHit(str(doc), sym, 1, "# Page")]
            banner = dd.render_banner(hits, "2026-05-21T13:17:00Z")
            self.assertTrue(dd.apply_banner(doc, banner))
            after_one = doc.read_text(encoding="utf-8")
            # Re-applying replaces, not stacks.
            banner2 = dd.render_banner(hits, "2026-05-22T13:17:00Z")
            self.assertTrue(dd.apply_banner(doc, banner2))
            after_two = doc.read_text(encoding="utf-8")
            self.assertEqual(
                after_one.count(dd.BANNER_BEGIN), 1,
                "first apply produced exactly one banner",
            )
            self.assertEqual(
                after_two.count(dd.BANNER_BEGIN), 1,
                "second apply does not stack banners",
            )
            self.assertIn("2026-05-22", after_two)
            self.assertNotIn("2026-05-21", after_two)


class ConfigTest(unittest.TestCase):
    def test_missing_config_uses_defaults(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            cfg = dd.load_config(Path(d) / "nope.yml")
            self.assertIn(".py", cfg["code_extensions"])
            self.assertIsInstance(cfg["ignore_symbols"], set)

    def test_overrides_apply(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.yml"
            p.write_text(
                "min_symbol_length: 8\n"
                "ignore_symbols: [get, set, foo]\n",
                encoding="utf-8",
            )
            cfg = dd.load_config(p)
            self.assertEqual(cfg["min_symbol_length"], 8)
            self.assertEqual(cfg["ignore_symbols"], {"get", "set", "foo"})


class ParseIsoTest(unittest.TestCase):
    def test_normalizes_z_and_offset(self) -> None:
        self.assertEqual(
            dd.parse_iso_timestamp("2026-05-01T00:00:00Z"),
            "2026-05-01T00:00:00Z",
        )
        self.assertEqual(
            dd.parse_iso_timestamp("2026-05-01T00:00:00+00:00"),
            "2026-05-01T00:00:00Z",
        )

    def test_invalid_since_exits(self) -> None:
        with self.assertRaises(SystemExit):
            dd.parse_iso_timestamp("not-a-date")


class ListMergedPrsTest(unittest.TestCase):
    def test_includes_late_merge_with_low_pr_number(self) -> None:
        class StubGitHub(dd.GitHub):
            def _request(self, url):
                return [
                    {
                        "number": 200,
                        "merged_at": "2026-05-20T12:00:00Z",
                        "updated_at": "2026-05-20T12:00:00Z",
                    },
                    {
                        "number": 5,
                        "merged_at": "2026-05-21T10:00:00Z",
                        "updated_at": "2026-05-21T10:00:00Z",
                    },
                ]

        gh = StubGitHub(None)
        prs = gh.list_merged_prs(
            "owner/repo",
            "main",
            since_iso="2026-05-19T00:00:00Z",
            max_prs=50,
        )
        numbers = [p["number"] for p in prs]
        self.assertIn(5, numbers)
        self.assertIn(200, numbers)


class EscapeMarkdownTest(unittest.TestCase):
    def test_escapes_link_breaking_characters(self) -> None:
        escaped = dd.escape_markdown_inline("Fix [broken] (title)")
        self.assertIn(r"\[", escaped)
        report = dd.render_report(
            [],
            "2026-05-21T13:17:00Z",
            [{
                "number": 1,
                "title": "Fix [broken] (title)",
                "html_url": "https://example.test/1",
                "merged_at": "2026-05-20T00:00:00Z",
                "user": {"login": "bot*name"},
            }],
            None,
        )
        self.assertIn(r"Fix \[broken\]", report)
        self.assertIn(r"bot\*name", report)


class StateTest(unittest.TestCase):
    def test_round_trip(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.json"
            self.assertIsNone(dd.load_state(p)["last_run_utc"])
            dd.save_state(p, {
                "last_run_utc": "2026-05-21T13:17:00Z",
                "last_pr_number": 42,
            })
            loaded = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(loaded["last_pr_number"], 42)


class CollectSymbolsTest(unittest.TestCase):
    def test_collect_dedupes_and_attaches_pr_metadata(self) -> None:
        class StubGitHub:
            def list_pr_files(self, repo, pr_number):
                if pr_number == 1:
                    return [{
                        "filename": "scripts/pipeline.py",
                        "patch": (
                            "@@ -1,1 +1,1 @@\n"
                            "-def IngestPipeline():\n"
                            "+def CorpusPipeline():\n"
                        ),
                    }]
                return [{
                    "filename": "docs/index.html",  # not a code file
                    "patch": "+CorpusPipeline reference",
                }]

        prs = [
            {"number": 1, "title": "Rename pipeline",
             "html_url": "u/1", "merged_at": "2026-05-20T00:00:00Z"},
            {"number": 2, "title": "Docs only",
             "html_url": "u/2", "merged_at": "2026-05-20T01:00:00Z"},
        ]
        cfg = dd.load_config(Path("nonexistent"))
        out = dd.collect_symbols(StubGitHub(), "owner/repo", prs, cfg)
        self.assertIn("CorpusPipeline", out)
        self.assertEqual(out["CorpusPipeline"].pr_number, 1)
        # Symbols-only-in-docs-files do not enter the surface.
        self.assertNotIn("docs", out)


if __name__ == "__main__":
    unittest.main()
