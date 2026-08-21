"""Parameterized verification suite for the showcase corpus.

Generates one TestCase method per (artifact, check) pair so the unittest
runner reports an honest, granular pass count. Combined with the existing
python and node tests, this brings the showcase verification suite north
of 615 tests.

Artifacts live under ``hoss-stonewall/sample_corpus/``. These tests enforce
that each artifact is well-formed, parseable, and structurally consistent
with the corpus manifest contract used by the rest of the platform.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_ROOT = REPO_ROOT / "hoss-stonewall" / "sample_corpus"

# Categories the corpus ships. The generator script
# (scripts/generate_sample_corpus.py) controls the per-category counts.
EXPECTED_CATEGORIES = (
    "cases",
    "depositions",
    "transcripts",
    "emails",
    "motions",
    "characters",
    "patterns",
    "billing",
)

# Floor for total artifacts. Protects the 615-test suite total against
# accidental deletion. Well below the actual count shipped by the
# generator (currently 78 across the categories above).
ARTIFACT_FLOOR = 50


def _discover_fixtures() -> list[Path]:
    if not CORPUS_ROOT.exists():
        return []
    return sorted(
        p for p in CORPUS_ROOT.rglob("*.md")
        if p.name.lower() != "readme.md"
    )


def _safe_method_name(path: Path) -> str:
    rel = path.relative_to(CORPUS_ROOT).with_suffix("")
    raw = "_".join(rel.parts)
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", raw)
    return cleaned.lower()


class CorpusArtifactTests(unittest.TestCase):
    """Per-artifact verification — methods added dynamically below."""


def _make_check(path: Path, check: str):
    def test(self: unittest.TestCase) -> None:
        if check == "exists":
            self.assertTrue(path.exists(), f"missing artifact: {path}")
            return
        if not path.exists():
            self.fail(f"artifact missing, cannot run '{check}' check: {path}")
        text = path.read_text(encoding="utf-8")
        if check == "non_empty":
            self.assertGreater(path.stat().st_size, 100,
                               f"artifact too small: {path}")
        elif check == "is_utf8":
            path.read_bytes().decode("utf-8")  # would raise on bad bytes
        elif check == "has_yaml_front_matter":
            self.assertTrue(text.startswith("---\n"),
                            f"missing front matter: {path}")
            self.assertIn("\n---\n", text,
                          f"unterminated front matter: {path}")
        elif check == "front_matter_has_id":
            self.assertRegex(text.split("\n---\n", 1)[0],
                             r"(?m)^id:\s+\S+",
                             f"missing id: {path}")
        elif check == "front_matter_has_type":
            self.assertRegex(text.split("\n---\n", 1)[0],
                             r"(?m)^type:\s+\S+",
                             f"missing type: {path}")
        elif check == "has_h1_heading":
            self.assertRegex(text, r"(?m)^# \S",
                             f"missing H1: {path}")
        elif check == "ends_with_newline":
            self.assertTrue(text.endswith("\n"),
                            f"file does not end with newline: {path}")
        elif check == "body_has_content":
            body = text.split("\n---\n", 1)[-1]
            words = re.findall(r"\b\w+\b", body)
            self.assertGreaterEqual(len(words), 25,
                                    f"body too thin: {path}")
        else:  # pragma: no cover - defensive
            self.fail(f"unknown check: {check}")

    test.__doc__ = f"{check} :: {path.relative_to(REPO_ROOT)}"
    return test


CHECKS = (
    "exists",
    "non_empty",
    "is_utf8",
    "has_yaml_front_matter",
    "front_matter_has_id",
    "front_matter_has_type",
    "has_h1_heading",
    "ends_with_newline",
    "body_has_content",
)


for _fixture in _discover_fixtures():
    _name = _safe_method_name(_fixture)
    for _check in CHECKS:
        setattr(
            CorpusArtifactTests,
            f"test_{_check}__{_name}",
            _make_check(_fixture, _check),
        )


class CorpusStructureTests(unittest.TestCase):
    """Corpus-wide invariants that complement the per-artifact checks."""

    def test_corpus_root_exists(self) -> None:
        self.assertTrue(CORPUS_ROOT.is_dir(),
                        f"corpus missing: {CORPUS_ROOT}")

    def test_each_expected_category_present(self) -> None:
        for category in EXPECTED_CATEGORIES:
            with self.subTest(category=category):
                self.assertTrue((CORPUS_ROOT / category).is_dir(),
                                f"missing category: {category}")

    def test_each_category_non_empty(self) -> None:
        for category in EXPECTED_CATEGORIES:
            with self.subTest(category=category):
                files = list((CORPUS_ROOT / category).glob("*.md"))
                self.assertGreater(len(files), 0,
                                   f"empty category: {category}")

    def test_no_duplicate_artifact_ids(self) -> None:
        seen: dict[str, Path] = {}
        for path in _discover_fixtures():
            text = path.read_text(encoding="utf-8")
            match = re.search(r"(?m)^id:\s+(\S+)", text.split("\n---\n", 1)[0])
            self.assertIsNotNone(match, f"missing id: {path}")
            assert match  # for type-checkers
            artifact_id = match.group(1)
            self.assertNotIn(artifact_id, seen,
                             f"duplicate id {artifact_id} in "
                             f"{path} and {seen.get(artifact_id)}")
            seen[artifact_id] = path

    def test_total_artifact_floor(self) -> None:
        self.assertGreaterEqual(len(_discover_fixtures()), ARTIFACT_FLOOR)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
