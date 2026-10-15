from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

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

    def test_packet_text_carries_no_record_text(self) -> None:
        code, out, _ = run("packet", QUESTION, "--channel", "model", "--limit", "4",
                           "--format", "text")
        self.assertEqual(code, 0)
        self.assertEqual(len(out.splitlines()), 5)
        self.assertNotIn("binder", out)
        self.assertNotIn("WITNESS", out)
        self.assertTrue(out.splitlines()[4].endswith("  confidential"))

    def test_unknown_channel_exits_two(self) -> None:
        code, out, err = run("packet", QUESTION, "--channel", "nope")
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(err, "stonewall: unknown_channel: nope\n")

    def test_checks_list_is_deterministic_and_runs_nothing(self) -> None:
        first = run("checks", "--list", "--repo", str(REPO_ROOT))
        self.assertEqual(first, run("checks", "--list", "--repo", str(REPO_ROOT)))
        self.assertEqual(first[0], 0)
        self.assertTrue(first[1].startswith("answers      answer-quote-drift"))


if __name__ == "__main__":
    unittest.main()
