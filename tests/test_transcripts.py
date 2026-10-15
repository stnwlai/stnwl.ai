from __future__ import annotations

import json
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

from stonewall.errors import TranscriptError
from stonewall.models import Finding
from stonewall.transcripts import (
    check_transcripts,
    parse_transcripts,
    publishable_file,
    render_command,
    write_transcripts,
)

README = PurePosixPath("README.md")
SENTINEL = 'The memo says "hold the copy" until the hearing ends.'
QUESTION = "Where was the original binder kept, and did it ever leave?"


def console(command: str, body: str = "") -> str:
    return f"```console\n$ {command}\n{body}```\n"


class TranscriptTests(unittest.TestCase):
    def setUp(self) -> None:
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        self.root = Path(raw.name)
        shutil.copytree(REPO_ROOT / "examples", self.root / "examples")
        memo = self.root / "examples/corpus/privileged/P0002_sentinel.md"
        memo.write_text(
            "---\nid: P0002\ntype: memo\ndate: 2025-01-01\ndesignation: privileged\n"
            f"---\n\n# Sentinel\n\n{SENTINEL}\n",
            encoding="utf-8",
        )
        (self.root / "note.txt").write_text("a public note\n", encoding="utf-8")
        (self.root / ".gitignore").write_text(".env\n", encoding="utf-8")
        (self.root / ".env").write_text("LOCAL=1\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)

    def readme(self, text: str) -> Path:
        path = self.root / "README.md"
        path.write_text(text, encoding="utf-8")
        return path

    def assert_rule(self, rule: str, function, *args) -> TranscriptError:
        with self.assertRaises(TranscriptError) as caught:
            function(*args)
        self.assertEqual(caught.exception.rule, rule)
        return caught.exception

    def test_parses_console_blocks(self) -> None:
        text = "# Title\n\n```bash\n$ not a transcript\n```\n\n" + console("cat note.txt", "x\n")
        (block,) = parse_transcripts(text)
        self.assertEqual((block.line, block.command), (7, "cat note.txt"))
        self.assertEqual(block.body, "$ cat note.txt\nx\n")
        self.assertEqual(text[block.start : block.end], block.body)

    def test_fence_closes_only_on_its_own_character_and_length(self) -> None:
        text = ("````text\n```\n$ cat hidden.txt\n```\n````\n\n~~~\n```console\n~~~\n\n"
                + console("cat note.txt", "x\n"))
        (block,) = parse_transcripts(text)
        self.assertEqual((block.line, block.command), (11, "cat note.txt"))
        self.assertEqual(parse_transcripts("````console\n$ cat note.txt\n````\n"), ())
        self.assert_rule("transcript_unterminated", parse_transcripts, "````text\n```\n")

    def test_unsupported_commands(self) -> None:
        for command in (
            "ls",
            "stonewall query x | head",
            "FOO=1 stonewall query x",
            "stonewall query x",
            "stonewall build",
            "stonewall checks",
            "stonewall transcripts --check README.md",
            "cat note.txt > copy.txt",
        ):
            with self.subTest(command=command):
                self.assert_rule("transcript_unsupported", render_command, self.root, command)

    def test_cat_rejects_noncanonical_paths(self) -> None:
        (self.root / "link.txt").symlink_to(self.root / "note.txt")
        for path in ("../x", "/etc/hosts", "a//b", "./note.txt", "link.txt", "examples"):
            with self.subTest(path=path):
                self.assert_rule("transcript_unsupported", render_command, self.root, f"cat {path}")
        for character in ("\x00", "\x01", "\t", "\x1f", "\x7f"):
            with self.subTest(character=repr(character)):
                error = self.assert_rule("transcript_unsupported", publishable_file,
                                         self.root, f"note{character}.txt")
                self.assertEqual(error.detail, "path is not canonical")
        self.assertEqual(render_command(self.root, "cat note.txt"), "$ cat note.txt\na public note\n")

    def test_commands_read_only_publishable_files(self) -> None:
        outside = self.root.parent / f"{self.root.name}-outside.md"
        shutil.copy(REPO_ROOT / "examples/answers/grounded.md", outside)
        self.addCleanup(outside.unlink)
        (self.root / "answer-link.md").symlink_to(self.root / "examples/answers/grounded.md")
        for command in (
            "cat .env",
            "cat .git/HEAD",
            f"stonewall audit-answer ../{outside.name}",
            f"stonewall audit-answer {outside}",
            "stonewall audit-answer ./examples/answers/grounded.md",
            "stonewall audit-answer answer-link.md",
            "stonewall audit-answer .env",
        ):
            with self.subTest(command=command):
                self.assert_rule("transcript_unsupported", render_command, self.root, command)
        rendered = render_command(self.root, "stonewall audit-answer examples/answers/grounded.md")
        self.assertIn("verdict  GROUNDED", rendered)
        self.assertEqual(publishable_file(self.root, "note.txt"), self.root / "note.txt")

    def test_crlf_document_is_unsupported(self) -> None:
        self.readme("Intro\n\n" + console("cat note.txt", "a public note\r\n"))
        error = self.assert_rule("transcript_unsupported", parse_transcripts,
                                 (self.root / "README.md").read_bytes().decode("utf-8"))
        self.assertEqual((error.detail, error.line), ("LF line endings required", 5))
        self.assertEqual(check_transcripts(self.root, README),
                         [Finding("README.md", 5, "transcript_unsupported")])

    def test_privileged_heading_and_escaped_whitespace_are_unpublishable(self) -> None:
        record = self.root / "examples/corpus/privileged/P0001_custody_advice.md"
        record.write_text(
            record.read_text(encoding="utf-8")
            .replace("is the weakest", "is the\tweakest")
            .replace("custody chain", "custody\tchain")
            .replace("explain why", "explain\twhy"),
            encoding="utf-8",
        )
        for command in (
            f'stonewall packet "{QUESTION}" --channel review --limit 4',
            "stonewall cite P0001:8-8 --channel review",
        ):
            with self.subTest(command=command):
                self.readme(console(command))
                self.assertEqual(check_transcripts(self.root, README),
                                 [Finding("README.md", 1, "transcript_unpublishable")])

    def test_backslash_before_restricted_text_is_unpublishable(self) -> None:
        line = "the memo was kept in the vault drawer overnight"
        memo = self.root / "examples/corpus/privileged/P0002_sentinel.md"
        template = memo.read_text(encoding="utf-8")
        for recorded in (line, "\\" + line):
            with self.subTest(recorded=recorded):
                memo.write_text(template.replace(SENTINEL, recorded), encoding="utf-8")
                (self.root / "shown.txt").write_text("\\" + line + "\n", encoding="utf-8")
                self.readme(console("cat shown.txt"))
                self.assertEqual(check_transcripts(self.root, README),
                                 [Finding("README.md", 1, "transcript_unpublishable")])

    def test_drift_reported_without_echoing_text(self) -> None:
        self.readme("Intro\n\n" + console("cat note.txt", "stale words\n"))
        findings = check_transcripts(self.root, README)
        self.assertEqual(findings, [Finding("README.md", 3, "transcript_drift")])
        self.assertNotIn("stale", findings[0].render())
        self.assertNotIn("public note", findings[0].render())

    def test_write_then_check_is_clean(self) -> None:
        path = self.readme("Intro\n\n" + console("cat note.txt") + "\nOutro\n")
        path.chmod(0o640)
        self.assertEqual(write_transcripts(self.root, README), 1)
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)
        self.assertEqual(check_transcripts(self.root, README), [])
        self.assertEqual(write_transcripts(self.root, README), 0)
        self.assertTrue(path.read_text(encoding="utf-8").endswith("a public note\n```\n\nOutro\n"))
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),
                         [".env", ".git", ".gitignore", "README.md", "examples", "note.txt"])

    def test_unterminated_block(self) -> None:
        self.readme("Intro\n\n```console\n$ cat note.txt\n")
        error = self.assert_rule("transcript_unterminated", parse_transcripts,
                                 (self.root / "README.md").read_text(encoding="utf-8"))
        self.assertEqual(error.line, 3)
        self.assertEqual(check_transcripts(self.root, README),
                         [Finding("README.md", 3, "transcript_unterminated")])

    def test_nonzero_exit_is_rendered(self) -> None:
        rendered = render_command(self.root, "stonewall cite Z9999:1-1")
        self.assertTrue(rendered.startswith("$ stonewall cite Z9999:1-1\n"))
        self.assertTrue(rendered.endswith("[exit 2]\n"))

    def test_block_carrying_privileged_text_is_unpublishable_and_never_written(self) -> None:
        leaks = {
            "plain.txt": SENTINEL + "\n",
            "escaped.txt": json.dumps(SENTINEL)[1:-1] + "\n",
            "wrapped.txt": SENTINEL.replace(" until", "\n   until") + "\n",
        }
        for name, content in leaks.items():
            with self.subTest(name=name):
                (self.root / name).write_text(content, encoding="utf-8")
                path = self.readme(console("cat note.txt") + console(f"cat {name}"))
                before = path.read_bytes()
                findings = check_transcripts(self.root, README)
                self.assertIn(Finding("README.md", 4, "transcript_unpublishable"), findings)
                self.assertNotIn("memo", repr(findings))
                self.assert_rule("transcript_unpublishable", write_transcripts, self.root, README)
                self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
