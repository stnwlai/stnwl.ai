from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from stonewall.checks import CHECKS
from stonewall.cli import main

QUESTION = "Where was the original binder kept, and did it ever leave?"
GLOBALS = [
    "--corpus", str(REPO_ROOT / "examples" / "corpus"),
    "--policy", str(REPO_ROOT / "examples" / "disclosure-policy.toml"),
    "--speakers", str(REPO_ROOT / "examples" / "speakers.toml"),
]


def run(*args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main([*GLOBALS, *args])
    return code, out.getvalue(), err.getvalue()


class CommandTests(unittest.TestCase):
    def test_audit_answer_exit_codes(self) -> None:
        answers = REPO_ROOT / "examples" / "answers"
        self.assertEqual(run("audit-answer", str(answers / "grounded.md"))[0], 0)
        code, out, _ = run("audit-answer", str(answers / "fabricated.md"))
        self.assertEqual(code, 1)
        self.assertIn("NOT GROUNDED", out)
        self.assertEqual(run("audit-answer", str(answers / "missing.md"))[0], 2)

    def test_build_reports_conflicting_output_without_changing_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "existing-file"
            output.write_bytes(b"keep this file")
            for destination in (output, output / "bundle"):
                with self.subTest(destination=destination.name):
                    code, out, err = run("build", "--output", str(destination))
                    self.assertEqual((code, out), (2, ""))
                    self.assertEqual(err, "stonewall: filesystem_error: FileExistsError\n")
                    self.assertEqual(output.read_bytes(), b"keep this file")
                    self.assertEqual(list(Path(raw).iterdir()), [output])

    def test_cite_refuses_oversized_line_numbers(self) -> None:
        previous_limit = sys.get_int_max_str_digits()
        try:
            sys.set_int_max_str_digits(4300)
            oversized = "9" * 5000
            for address in (f"T0002:{oversized}", f"T0002:12-{oversized}"):
                with self.subTest(position="end" if "-" in address else "start"):
                    code, out, err = run("cite", address)
                    self.assertEqual((code, out), (2, ""))
                    self.assertEqual(err, "stonewall: citation address is malformed\n")
        finally:
            sys.set_int_max_str_digits(previous_limit)

    def test_cite_prints_verified_lines(self) -> None:
        code, out, _ = run("cite", "T0002:15-15")
        self.assertEqual(code, 0)
        rows = out.splitlines()
        self.assertTrue(rows[0].startswith("T0002:15-15@"))
        self.assertTrue(rows[0].endswith("  transcripts/T0002_custody.md  public"))
        self.assertTrue(rows[1].startswith("  15  THE WITNESS: It left once."))

    def test_cite_refuses_wrong_pin_and_out_of_body_range(self) -> None:
        for address in ("T0002:12-15@000000000000", "T0002:2-2", "P0001:12-13@x"):
            code, out, err = run("cite", address)
            self.assertEqual(code, 2, address)
            self.assertEqual(out, "")
            self.assertTrue(err.startswith("stonewall: citation "), address)

    def test_cite_outside_channel_view_is_unknown(self) -> None:
        code, _, err = run("cite", "P0001:12-13", "--channel", "model")
        self.assertEqual(code, 2)
        self.assertEqual(err, "stonewall: citation artifact is unknown\n")

    def test_query_and_cite_default_to_the_publish_channel(self) -> None:
        self.assertEqual(run("cite", "P0001:12-13"),
                         (2, "", "stonewall: citation artifact is unknown\n"))
        code, out, _ = run("cite", "P0001:12-13", "--channel", "review")
        self.assertEqual(code, 0)
        self.assertTrue(out.splitlines()[0].endswith("  privileged"))
        code, out, _ = run("query", "weakest link custody", "--limit", "1")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["channel"], "publish")
        self.assertNotIn("P0001", out)

    def test_transcripts_document_must_be_publishable(self) -> None:
        with contextlib.chdir(REPO_ROOT):
            for document in ("./README.md", "/etc/hostname", "../README.md", "missing.md"):
                with self.subTest(document=document):
                    code, out, err = run("transcripts", "--check", document)
                    self.assertEqual((code, out), (2, ""))
                    self.assertIn("[transcript_unsupported]", err)

    def test_transcripts_document_outside_candidate_set_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / ".gitignore").write_text("build/\n", encoding="utf-8")
            (root / "build").mkdir()
            (root / "build" / "notes.md").write_text("Notes\n", encoding="utf-8")
            with contextlib.chdir(root):
                code, out, err = run("transcripts", "--check", "build/notes.md")
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(err, "stonewall: [transcript_unsupported] build/notes.md\n")

    def test_packet_text_carries_no_record_text(self) -> None:
        code, out, _ = run("packet", QUESTION, "--channel", "model", "--limit", "4",
                           "--format", "text")
        self.assertEqual(code, 0)
        header, *rows = out.splitlines()
        self.assertRegex(
            header, r"^packet  [0-9a-f]{12}  channel model  limit 4  view [0-9a-f]{12}$"
        )
        self.assertEqual(len(rows), 4)
        for row in rows:
            self.assertRegex(
                row,
                r"^S[1-9][0-9]*  [A-Z][A-Z0-9_-]*[0-9]{4}:[0-9]+-[0-9]+@[0-9a-f]{12}  "
                r"(public|confidential|privileged)$",
            )
        self.assertTrue(rows[3].endswith("  confidential"))

    def test_unknown_channel_exits_two(self) -> None:
        code, out, err = run("packet", QUESTION, "--channel", "nope")
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(err, "stonewall: unknown_channel: nope\n")

    def test_checks_list_is_deterministic_and_runs_nothing(self) -> None:
        first = run("checks", "--list", "--repo", str(REPO_ROOT))
        self.assertEqual(first, run("checks", "--list", "--repo", str(REPO_ROOT)))
        self.assertEqual(first[0], 0)
        self.assertTrue(first[1].startswith("answers      answer-quote-drift"))
        lines = first[1].splitlines()
        for line in lines:
            self.assertRegex(line, r"^\S+\s+\S+\s+\S+$")
        self.assertEqual({line.split()[0] for line in lines}, {check.name for check in CHECKS})


if __name__ == "__main__":
    unittest.main()
