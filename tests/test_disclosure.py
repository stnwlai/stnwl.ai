from __future__ import annotations

import itertools
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from stonewall.compiler import compile_corpus, corpus_root_digest
from stonewall.disclosure import (
    DisclosurePolicy,
    channel_view,
    decide,
    load_policy,
    unknown_designations,
    unpublishable_lines,
    view_digest,
)
from stonewall.errors import DisclosureError
from stonewall.retrieval import query_corpus

CORPUS_ROOT = REPO_ROOT / "examples" / "corpus"
POLICY_PATH = REPO_ROOT / "examples" / "disclosure-policy.toml"
QUESTION = "Where was the original binder kept, and did it ever leave?"
DESIGNATIONS = ("public", "confidential", "privileged")


def record(artifact_id: str, designation: str, body: str) -> str:
    return (
        f"---\nid: {artifact_id}\ntype: note\ndate: 2025-01-01\n"
        f"designation: {designation}\n---\n\n{body}\n"
    )


def corpus_copy(raw: str, *, drop_privileged: bool = False) -> Path:
    root = Path(raw) / "corpus"
    shutil.copytree(CORPUS_ROOT, root)
    if drop_privileged:
        shutil.rmtree(root / "privileged")
    return root


class PolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_policy(POLICY_PATH)
        self.reference = POLICY_PATH.read_text(encoding="utf-8")

    def load_text(self, text: str) -> DisclosurePolicy:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "policy.toml"
            path.write_text(text, encoding="utf-8")
            return load_policy(path)

    def assert_rule(self, text: str, rule: str) -> None:
        with self.assertRaises(DisclosureError) as caught:
            self.load_text(text)
        self.assertEqual(caught.exception.rule, rule)

    def edited(self, old: str, new: str) -> str:
        self.assertIn(old, self.reference)
        return self.reference.replace(old, new)

    def test_reference_policy_loads(self) -> None:
        self.assertEqual(self.policy.channels, ("model", "publish", "review"))
        self.assertEqual(self.policy.digest, load_policy(POLICY_PATH).digest)
        self.assertEqual(self.policy.designations, DESIGNATIONS)

    def test_permission_table_is_fixed(self) -> None:
        expected = {
            ("public", "model"): True,
            ("public", "publish"): True,
            ("public", "review"): True,
            ("confidential", "model"): True,
            ("confidential", "publish"): False,
            ("confidential", "review"): True,
            ("privileged", "model"): False,
            ("privileged", "publish"): False,
            ("privileged", "review"): True,
        }
        actual = {
            (designation, channel): self.policy.permits(designation, channel)
            for designation in DESIGNATIONS
            for channel in self.policy.channels
        }
        self.assertEqual(actual, expected)

    def test_join_is_most_restrictive_and_order_independent(self) -> None:
        for size in range(1, 4):
            for subset in itertools.combinations(DESIGNATIONS, size):
                expected = max(subset, key=DESIGNATIONS.index)
                for order in itertools.permutations(subset):
                    self.assertEqual(self.policy.join(order), expected)
                    self.assertIsNone(self.policy.join((*order, "secret")))
        self.assertIsNone(self.policy.join(()))

    def test_decide_reasons(self) -> None:
        cases = (
            (["public"], "publish", "allowed", "public"),
            (["public", "privileged"], "model", "exceeds_ceiling", "privileged"),
            (["public", "Privileged"], "review", "unknown_designation", None),
            (["public"], "email", "unknown_channel", "public"),
            ([], "review", "no_sources", None),
            # Precedence pairs.
            ([], "email", "unknown_channel", None),
            (["Secret"], "email", "unknown_channel", None),
            (["privileged"], "email", "unknown_channel", "privileged"),
            (["privileged", "Secret"], "publish", "unknown_designation", None),
        )
        for designations, channel, reason, joined in cases:
            decision = decide(self.policy, iter(designations), channel)
            self.assertEqual(decision.reason, reason, (designations, channel))
            self.assertEqual(decision.designation, joined)
            self.assertEqual(decision.allowed, reason == "allowed")
            self.assertEqual(decision.to_dict()["reason"], reason)

    def test_case_variant_designation_is_unknown(self) -> None:
        for designation in ("Privileged", "PRIVILEGED", "privileged_"):
            for channel in self.policy.channels:
                self.assertFalse(self.policy.permits(designation, channel))
                self.assertFalse(decide(self.policy, [designation], channel).allowed)

    def test_loosened_policy_is_refused(self) -> None:
        texts = (
            self.edited('model = "confidential"', 'model = "privileged"'),
            self.edited('publish = "public"', 'publish = "confidential"'),
            self.edited(
                '["public", "confidential", "privileged"]',
                '["privileged", "confidential", "public"]',
            ),
            self.edited(', "privileged"]', "]").replace('review = "privileged"\n', ""),
        )
        for text in texts:
            self.assert_rule(text, "fixed_decision_violated")

    def test_policy_shape_errors(self) -> None:
        for text in (
            self.edited("version = 1", "version = 2"),
            self.edited("version = 1", "version = true"),
            self.edited('"privileged"]', '"privileged", "public"]'),
            self.edited('"confidential",', '"Confidential",'),
            self.edited("version = 1", "version = 1\nextra = 1"),
            "version = [",
        ):
            self.assert_rule(text, "policy_invalid")
        self.assert_rule(
            self.edited('review = "privileged"', 'review = "secret"'), "unknown_ceiling"
        )
        with self.assertRaises(DisclosureError) as caught:
            load_policy(REPO_ROOT / "examples" / "missing-policy.toml")
        self.assertEqual(caught.exception.rule, "policy_invalid")


class ViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_policy(POLICY_PATH)
        self.corpus = compile_corpus(CORPUS_ROOT)

    def excluded(self, channel: str) -> set[str]:
        view = channel_view(self.corpus, self.policy, channel)
        kept = {artifact.artifact_id for artifact in view.artifacts}
        self.assertTrue(all(chunk.artifact_id in kept for chunk in view.chunks))
        return {artifact.artifact_id for artifact in self.corpus.artifacts} - kept

    def test_views_exclude_records_above_ceiling(self) -> None:
        self.assertEqual(self.excluded("model"), {"P0001"})
        self.assertEqual(self.excluded("publish"), {"D0001", "D0002", "P0001"})
        self.assertEqual(self.excluded("review"), set())
        with self.assertRaises(DisclosureError) as caught:
            channel_view(self.corpus, self.policy, "email")
        self.assertEqual(caught.exception.rule, "unknown_channel")

    def test_unknown_designation_refuses_every_view(self) -> None:
        sentinel = "The sentinel sentence must never appear in a refusal."
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "A0001_note.md").write_text(
                record("A0001", "public", "# Note\n\nPublic text."), encoding="utf-8"
            )
            (root / "Z0001_note.md").write_text(
                record("Z0001", "Privileged", f"# Note\n\n{sentinel}"), encoding="utf-8"
            )
            corpus = compile_corpus(root)
        self.assertEqual(unknown_designations(corpus, self.policy), ("Z0001",))
        for channel in self.policy.channels:
            with self.assertRaises(DisclosureError) as caught:
                channel_view(corpus, self.policy, channel)
            self.assertEqual(caught.exception.rule, "unknown_designation")
            self.assertIn("Z0001", str(caught.exception))
            self.assertNotIn("sentinel", str(caught.exception))

    def test_view_scores_equal_corpus_without_privileged_records(self) -> None:
        view = channel_view(self.corpus, self.policy, "model")
        with tempfile.TemporaryDirectory() as raw:
            reduced = compile_corpus(corpus_copy(raw, drop_privileged=True))
            expected = [hit.to_dict() for hit in query_corpus(reduced, QUESTION, limit=20)]
        actual = [hit.to_dict() for hit in query_corpus(view, QUESTION, limit=20)]
        self.assertTrue(actual)
        self.assertEqual(actual, expected)

    def test_view_digest_ignores_records_outside_view(self) -> None:
        digest = view_digest(channel_view(self.corpus, self.policy, "model"))
        self.assertNotEqual(digest, corpus_root_digest(self.corpus.artifacts))
        with tempfile.TemporaryDirectory() as raw:
            root = corpus_copy(raw)
            advice = root / "privileged" / "P0001_custody_advice.md"
            advice.write_text(
                record("P0001", "privileged", "# Advice\n\nOriginal binder kept, never left."),
                encoding="utf-8",
            )
            rewritten = channel_view(compile_corpus(root), self.policy, "model")
            self.assertEqual(view_digest(rewritten), digest)
            shutil.rmtree(root / "privileged")
            removed = channel_view(compile_corpus(root), self.policy, "model")
            self.assertEqual(view_digest(removed), digest)

    def test_unpublishable_lines_skip_headings_and_short_lines(self) -> None:
        body = (
            "# Advice\n\n## Notes\n\nToo short to count.\n\nExactly twenty chars\n\n"
            "This   line is long enough\n   to be detected."
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "A0001_note.md").write_text(
                record("A0001", "public", "# Note\n\nA public line that is long enough."),
                encoding="utf-8",
            )
            (root / "P0001_note.md").write_text(
                record("P0001", "privileged", body), encoding="utf-8"
            )
            lines = unpublishable_lines(compile_corpus(root), self.policy)
        self.assertEqual(
            lines,
            (
                ("P0001", "Exactly twenty chars"),
                ("P0001", "This line is long enough"),
            ),
        )
        reference = unpublishable_lines(self.corpus, self.policy)
        self.assertEqual({item for item, _text in reference}, {"D0001", "D0002", "P0001"})
        advice = "Prepare the witness to explain why the copy was kept outside the records room."
        self.assertIn(("P0001", advice), reference)


if __name__ == "__main__":
    unittest.main()
