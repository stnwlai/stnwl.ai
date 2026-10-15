from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from stonewall.checks import (
    CHECKS,
    UNIT_TESTS,
    Check,
    SeededDefect,
    apply_defect,
    check_answers,
    check_corpus,
    check_disclosure,
    check_speakers,
    check_unit,
    load_defects,
    run_checks,
    snapshot_tree,
    stage_tree,
)
from stonewall.errors import CheckHarnessError
from stonewall.hashing import canonical_json_bytes
from stonewall.layout import DEFECTS_FILE
from stonewall.models import Finding
from stonewall.publication import candidate_paths

VALUE_DEFECT = """
[[defects]]
name = "value-drift"
check = "value"
expect = "value_changed"
op = "replace"
path = "data/value.txt"
old = "ok"
new = "no"
"""


def value_check(root: Path, scratch: Path) -> list[Finding]:
    if (root / "data" / "value.txt").read_text(encoding="utf-8") != "ok\n":
        return [Finding("data/value.txt", 1, "value_changed")]
    return []


def other_rule_check(root: Path, scratch: Path) -> list[Finding]:
    return [Finding("data/value.txt", 1, "other_rule")] if value_check(root, scratch) else []


def blind_check(root: Path, scratch: Path) -> list[Finding]:
    (scratch / "notes.txt").write_text("scratch is outside the tree\n", encoding="utf-8")
    return []


def crashing_check(root: Path, scratch: Path) -> list[Finding]:
    raise RuntimeError("synthetic crash")


UNIT_METHOD = "test_loosened_policy_is_refused"


def unit_defect(name: str, new: str) -> str:
    return f"""
[[defects]]
name = "{name}"
check = "unit"
expect = "{UNIT_METHOD}"
op = "replace"
path = "src/sample.py"
old = "return 1"
new = "{new}"
"""


class HarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        self.base = Path(raw.name)
        self.repo = self.base / "repo"
        (self.repo / "data").mkdir(parents=True)
        (self.repo / "ignored").mkdir()
        (self.repo / ".gitignore").write_text("ignored/\n", encoding="utf-8")
        (self.repo / "data" / "value.txt").write_text("ok\n", encoding="utf-8")
        (self.repo / "data" / "value.txt").chmod(0o644)
        (self.repo / "ignored" / "local.txt").write_text("local\n", encoding="utf-8")
        tool = self.repo / "tool.sh"
        tool.write_text("#!/bin/sh\n", encoding="utf-8")
        tool.chmod(0o755)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)

    def defects_file(self, *entries: str) -> Path:
        path = self.base / "defects.toml"
        path.write_text("version = 1\n" + "".join(entries), encoding="utf-8")
        return path

    def run_with(self, *checks: Check, defects: str = VALUE_DEFECT):
        return run_checks(self.repo, defects_path=self.defects_file(defects), checks=checks)

    def test_staged_copy_keeps_tracked_files_an_ignore_rule_matches(self) -> None:
        (self.repo / "data" / "kept.txt").write_text("kept\n", encoding="utf-8")
        subprocess.run(["git", "add", "-f", "data/kept.txt"], cwd=self.repo, check=True)
        (self.repo / ".gitignore").write_text("ignored/\ndata/kept.txt\n", encoding="utf-8")
        staged = self.base / "staged"
        stage_tree(self.repo, staged)
        self.assertIn(PurePosixPath("data/kept.txt"), candidate_paths(self.repo))
        self.assertEqual(candidate_paths(staged), candidate_paths(self.repo))

    def test_staged_tree_is_the_publishable_candidate_set(self) -> None:
        staged = self.base / "staged"
        stage_tree(self.repo, staged)
        snapshot = snapshot_tree(staged)
        self.assertEqual(sorted(snapshot), [".", ".gitignore", "data", "data/value.txt", "tool.sh"])
        self.assertTrue(snapshot["tool.sh"].endswith(":0755"))
        self.assertTrue(snapshot["data/value.txt"].endswith(":0644"))
        self.assertTrue((staged / ".git").is_dir())

    def test_unmodified_copy_passes_on_synthetic_tree(self) -> None:
        report = self.run_with(Check("value", value_check))
        self.assertTrue(report.passed)
        self.assertEqual(report.defects[0].status, "rejected")
        self.assertEqual(report.render_text().splitlines()[-1], "PASS")

    def test_tree_write_is_reported(self) -> None:
        def make(action):
            def run(root: Path, scratch: Path) -> list[Finding]:
                action(root)
                return value_check(root, scratch)
            return run

        actions = (
            ("data/new.txt", lambda root: (root / "data" / "new.txt").write_text("x")),
            ("tool.sh", lambda root: (root / "tool.sh").unlink()),
            ("data/value.txt", lambda root: (root / "data" / "value.txt").chmod(0o755)),
            ("data/value.txt", lambda root: (root / "data" / "value.txt").chmod(0o600)),
            ("empty", lambda root: (root / "empty").mkdir()),
            ("data", lambda root: (root / "data").chmod(0o700)),
        )
        for expected, action in actions:
            with self.subTest(expected=expected):
                report = self.run_with(Check("value", make(action)))
                self.assertEqual(report.clean[0].wrote, (expected,))
                self.assertEqual(report.defects[0].status, "wrote_tree")
                self.assertFalse(report.passed)
                self.assertIn("WROTE", report.render_text())

    def test_check_failing_unmodified_copy_fails_report(self) -> None:
        (self.repo / "data" / "value.txt").write_text("ok?\n", encoding="utf-8")
        report = self.run_with(Check("value", value_check))
        self.assertEqual(report.clean[0].rules, ("value_changed",))
        self.assertFalse(report.passed)

    def test_defect_rejected_for_expected_rule(self) -> None:
        report = self.run_with(Check("value", value_check))
        self.assertEqual(report.defects[0].rules, ("value_changed",))
        self.assertEqual(report.to_dict()["checks"][0]["rejected"], 1)

    def test_surviving_defect_is_reported(self) -> None:
        report = self.run_with(Check("value", blind_check))
        self.assertEqual(report.defects[0].status, "survived")
        self.assertIn("SURVIVED value-drift (value expected value_changed, saw: none)",
                      report.render_text())
        self.assertFalse(report.passed)

    def test_failure_rows_carry_rule_ids_and_locations(self) -> None:
        report = self.run_with(Check("value", other_rule_check))
        self.assertIn("saw: other_rule data/value.txt:1)", report.render_text())
        self.assertEqual(
            report.to_dict()["defects"][0]["findings"],
            [{"line": 1, "path": "data/value.txt", "rule": "other_rule"}],
        )
        (self.repo / "data" / "value.txt").write_text("ok?\n", encoding="utf-8")
        report = self.run_with(Check("value", value_check))
        self.assertIn("saw: value_changed data/value.txt:1", report.render_text())

    def test_defect_failing_for_other_rule_is_wrong_reason(self) -> None:
        report = self.run_with(Check("value", other_rule_check))
        self.assertEqual(report.defects[0].status, "wrong_reason")
        self.assertFalse(report.passed)

    def test_crashing_check_is_reported(self) -> None:
        report = self.run_with(Check("value", crashing_check))
        self.assertEqual(report.clean[0].rules, ("check_crashed",))
        self.assertEqual(report.defects[0].status, "check_crashed")
        self.assertFalse(report.passed)

    def test_unit_check_counts_only_assertion_failures(self) -> None:
        (self.repo / "src").mkdir()
        (self.repo / "src" / "sample.py").write_text("def value():\n    return 1\n")
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "test_sample.py").write_text(
            "import unittest\n\nfrom sample import value\n\n\n"
            "class PolicyTests(unittest.TestCase):\n"
            f"    def {UNIT_METHOD}(self):\n"
            "        self.assertEqual(value(), 1)\n"
        )
        test_id = f"tests.test_sample.PolicyTests.{UNIT_METHOD}"
        unit = Check("unit", lambda root, scratch: check_unit(root, scratch, unit_tests=(test_id,)))
        report = self.run_with(
            unit,
            defects=unit_defect("asserts", "return 2") + unit_defect("errors", "return missing"),
        )
        self.assertTrue(report.clean[0].passed)
        statuses = {d.name: (d.status, d.rules) for d in report.defects}
        self.assertEqual(statuses["asserts"], ("rejected", (UNIT_METHOD,)))
        self.assertEqual(statuses["errors"], ("wrong_reason", ("unit_errored",)))

    def test_stale_defect_raises(self) -> None:
        tree = self.base / "tree"
        (tree / "data").mkdir(parents=True)
        (tree / "data" / "value.txt").write_text("ok ok\n", encoding="utf-8")
        stale = (
            SeededDefect("a", "value", "r", "replace", PurePosixPath("data/value.txt"), "absent"),
            SeededDefect("b", "value", "r", "replace", PurePosixPath("data/value.txt"), "ok"),
            SeededDefect("c", "value", "r", "write", PurePosixPath("data/value.txt"), parts=("x",)),
            SeededDefect("d", "value", "r", "append", PurePosixPath("data/none.txt"), parts=("x",)),
        )
        for defect in stale:
            message = f"no longer applies: {defect.name}"
            with self.subTest(defect=defect.name), self.assertRaisesRegex(CheckHarnessError, message):
                apply_defect(tree, defect)
        self.assertEqual((tree / "data" / "value.txt").read_text(encoding="utf-8"), "ok ok\n")

    def test_check_without_defect_is_unchallenged(self) -> None:
        report = self.run_with(Check("value", value_check), Check("blind", blind_check))
        self.assertEqual(report.unchallenged, ("blind",))
        self.assertIn("UNCHALLENGED blind", report.render_text())
        self.assertFalse(report.passed)

    def test_defect_runs_never_touch_the_source_tree(self) -> None:
        before = snapshot_tree(self.repo)
        self.run_with(Check("value", value_check))
        self.assertEqual(snapshot_tree(self.repo), before)

    def test_load_defects_rejects_noncanonical_paths(self) -> None:
        checks = (Check("value", value_check),)
        for path in ("../x", "/x", "a\\b", "./a", "a//b", "", "a\x00b", "a\tb", "a\x1fb",
                     "a\x7fb"):
            # TOML escapes, so the loaded path holds the real character.
            quoted = "".join(
                c if c.isprintable() and c not in '"\\' else f"\\u{ord(c):04x}" for c in path
            )
            entry = VALUE_DEFECT.replace('"data/value.txt"', f'"{quoted}"')
            with self.subTest(path=path):
                with self.assertRaisesRegex(CheckHarnessError, "path is not canonical"):
                    load_defects(self.defects_file(entry), checks=checks)

    def test_load_defects_rejects_bad_shapes(self) -> None:
        checks = (Check("value", value_check), Check("unit", blind_check))
        cases = (
            VALUE_DEFECT + VALUE_DEFECT,
            VALUE_DEFECT.replace('check = "value"', 'check = "nope"'),
            VALUE_DEFECT.replace('op = "replace"', 'op = "delete"'),
            VALUE_DEFECT.replace('old = "ok"', 'old = ""'),
            VALUE_DEFECT.replace('op = "replace"', 'op = "append"'),
            VALUE_DEFECT.replace('check = "value"', 'check = "unit"'),
            VALUE_DEFECT.replace('new = "no"', 'new = "no"\nparts = "x"'),
            VALUE_DEFECT.replace('new = "no"', 'new = "no"\nparts = ["x"]'),
            VALUE_DEFECT.replace('op = "replace"', 'op = "append"')
            .replace('old = "ok"\nnew = "no"', 'parts = ["x", 1]'),
        )
        for entry in cases:
            with self.subTest(entry=entry), self.assertRaises(CheckHarnessError):
                load_defects(self.defects_file(entry), checks=checks)
        for version in ("2", "true", "1.0"):
            path = self.defects_file(VALUE_DEFECT)
            path.write_text(path.read_text().replace("version = 1", f"version = {version}"))
            with self.subTest(version=version), self.assertRaises(CheckHarnessError):
                load_defects(path, checks=checks)
        entry = VALUE_DEFECT.replace('expect = "value_changed"', 'expect = "Value-Changed"')
        with self.assertRaisesRegex(CheckHarnessError, "expects an invalid rule id: value-drift"):
            load_defects(self.defects_file(entry), checks=checks)

    def test_in_process_check_cannot_target_src(self) -> None:
        entry = VALUE_DEFECT.replace('"data/value.txt"', '"src/stonewall/models.py"')
        with self.assertRaisesRegex(CheckHarnessError, "cannot see src"):
            load_defects(self.defects_file(entry), checks=(Check("value", value_check),))

    def test_report_is_deterministic(self) -> None:
        first = self.run_with(Check("value", value_check))
        second = self.run_with(Check("value", value_check))
        self.assertEqual(canonical_json_bytes(first.to_dict()), canonical_json_bytes(second.to_dict()))
        self.assertEqual(first.render_text(), second.render_text())

    def test_data_checks_report_rule_ids_and_paths_only(self) -> None:
        tree = self.base / "tree"
        shutil.copytree(REPO_ROOT / "examples", tree / "examples")
        for check in (check_corpus, check_disclosure, check_speakers):
            self.assertEqual(check(tree, self.base), [])
        record = tree / "examples/corpus/privileged/P0001_custody_advice.md"
        record.write_text(record.read_text().replace(": privileged", ": Privileged"))
        self.assertEqual(
            check_disclosure(tree, self.base),
            [Finding("examples/corpus/privileged/P0001_custody_advice.md", 0, "unknown_designation")],
        )
        os.remove(tree / "examples/speakers.toml")
        self.assertEqual(check_speakers(tree, self.base)[0].rule, "registry_invalid")

    def test_corpus_check_names_the_violated_invariant(self) -> None:
        tree = self.base / "tree"
        shutil.copytree(REPO_ROOT / "examples", tree / "examples")
        record = tree / "examples/corpus/correspondence/E0002_availability.md"
        record.write_text(record.read_text().replace("id: E0002", "id: E0001"))
        self.assertEqual(
            check_corpus(tree, self.base),
            [Finding("examples/corpus", 0, "duplicate_artifact_id")],
        )

    def test_missing_or_empty_answers_are_unavailable(self) -> None:
        tree = self.base / "tree"
        shutil.copytree(REPO_ROOT / "examples", tree / "examples")
        self.assertEqual(check_answers(tree, self.base), [])
        for answer in (tree / "examples/answers").glob("*.md"):
            answer.unlink()
        unavailable = [Finding("examples/answers", 0, "answers_unavailable")]
        self.assertEqual(check_answers(tree, self.base), unavailable)
        (tree / "examples/answers").rmdir()
        self.assertEqual(check_answers(tree, self.base), unavailable)

    def test_nested_answer_is_audited(self) -> None:
        tree = self.base / "tree"
        shutil.copytree(REPO_ROOT / "examples", tree / "examples")
        nested = tree / "examples/answers/more/extra.md"
        nested.parent.mkdir()
        grounded = (tree / "examples/answers/grounded.md").read_text(encoding="utf-8")
        nested.write_text(grounded + "\nThe binder burned.\n", encoding="utf-8")
        self.assertEqual({(f.path, f.rule) for f in check_answers(tree, self.base)},
                         {("examples/answers/more/extra.md", "uncited_claim")})

    def test_reference_defects_file_is_consistent(self) -> None:
        defects = load_defects(REPO_ROOT / DEFECTS_FILE)
        self.assertEqual({check.name for check in CHECKS}, {d.check for d in defects})
        methods = {test.rsplit(".", 1)[1] for test in UNIT_TESTS}
        for defect in defects:
            target = REPO_ROOT / defect.path
            with self.subTest(defect=defect.name):
                if defect.op == "replace":
                    self.assertEqual(target.read_text(encoding="utf-8").count(defect.old), 1)
                elif defect.op == "write":
                    self.assertFalse(target.exists())
                else:
                    self.assertTrue(target.is_file())
                if defect.check == "unit":
                    self.assertIn(defect.expect, methods)


if __name__ == "__main__":
    unittest.main()
