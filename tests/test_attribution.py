from __future__ import annotations

import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from stonewall.attribution import (
    load_speakers,
    speaker_of,
    speaker_turns,
    unregistered_labels,
)
from stonewall.compiler import compile_corpus
from stonewall.errors import SpeakerRegistryError

CORPUS_ROOT = REPO_ROOT / "examples" / "corpus"
SPEAKERS_PATH = REPO_ROOT / "examples" / "speakers.toml"
REGISTRY = load_speakers(SPEAKERS_PATH)
SPAN = (
    "EXAMINING COUNSEL: So the original never left\n"
    "the records room?\n"
    "THE WITNESS: It left once.\n"
    "\n"
    "## Review\n"
    "EXAMINING COUNSEL: Did anyone compare the copy?\n"
    "# Heading\n"
    "Trailing prose."
)


class AttributionTests(unittest.TestCase):
    def registry_error(self, body: str) -> SpeakerRegistryError:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "speakers.toml"
            path.write_text("version = 1\n" + body, encoding="utf-8")
            with self.assertRaises(SpeakerRegistryError) as caught:
                load_speakers(path)
        return caught.exception

    def label(self, text: str) -> str | None:
        mention = REGISTRY.attribution(text)
        return mention.label if mention else None

    def test_registry_rejects_alias_shared_by_two_speakers(self) -> None:
        error = self.registry_error(
            '[[speakers]]\nlabel = "A"\naliases = ["shared alias"]\n'
            '[[speakers]]\nlabel = "B"\naliases = ["b", "shared alias"]\n'
        )
        self.assertEqual(error.rule, "ambiguous_alias")
        self.assertNotIn("shared alias", str(error))

    def test_registry_rejects_noncanonical_label_and_alias(self) -> None:
        for label, aliases in (
            ("a", '["a"]'),
            ("THE  WITNESS", '["witness"]'),
            ("A", '["Witness"]'),
            ("A", "[]"),
        ):
            with self.subTest(label=label, aliases=aliases):
                body = f'[[speakers]]\nlabel = "{label}"\naliases = {aliases}\n'
                self.assertEqual(self.registry_error(body).rule, "registry_invalid")

    def test_registry_rejects_unknown_keys_and_invalid_toml(self) -> None:
        speaker = '[[speakers]]\nlabel = "A"\naliases = ["a"]\n'
        for body in ("extra = 1\n" + speaker, speaker + "role = 'x'\n", "speakers = [\n"):
            with self.subTest(body=body):
                self.assertEqual(self.registry_error(body).rule, "registry_invalid")

    def test_mentions_prefer_longest_alias(self) -> None:
        text = "defending counsel stated"
        raw = tomllib.loads(SPEAKERS_PATH.read_text(encoding="utf-8"))
        naive = next(
            entry["label"]
            for entry in raw["speakers"]
            for alias in entry["aliases"]
            if text.find(alias) != -1
        )
        self.assertEqual(naive, "EXAMINING COUNSEL")
        self.assertEqual([m.label for m in REGISTRY.mentions(text)], ["DEFENDING COUNSEL"])
        self.assertNotEqual(self.label(text), naive)

    def test_registry_version_must_be_the_integer_one(self) -> None:
        speaker = '[[speakers]]\nlabel = "A"\naliases = ["a"]\n'
        for version in ("1.0", "true"):
            with self.subTest(version=version):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "speakers.toml"
                    path.write_text(f"version = {version}\n{speaker}", encoding="utf-8")
                    with self.assertRaises(SpeakerRegistryError) as caught:
                        load_speakers(path)
                self.assertEqual(caught.exception.rule, "registry_invalid")

    def test_mentions_respect_word_boundaries(self) -> None:
        for text in ("the eyewitness said", "witnesses said", "counselor said",
                     "the witness\u00e9 said"):
            with self.subTest(text=text):
                self.assertEqual(REGISTRY.mentions(text), ())

    def test_mentions_span_line_breaks(self) -> None:
        self.assertEqual(self.label("the\nwitness answered"), "THE WITNESS")

    def test_attribution_requires_adjacent_verb(self) -> None:
        for text in ("Counsel's outline", "the witness also testified", "counsel to",
                     "Counsel asked the witness", "The witness, when counsel asked, testified "):
            with self.subTest(text=text):
                self.assertIsNone(REGISTRY.attribution(text))
        self.assertEqual(self.label("Counsel asked "), "EXAMINING COUNSEL")
        self.assertEqual(self.label("The witness testifies that\n"), "THE WITNESS")
        self.assertEqual(self.label("Defense counsel said, "), "DEFENDING COUNSEL")

    def test_possessive_mention_does_not_bind(self) -> None:
        for text in ("the witness's counsel said ", "the witness\u2019s counsel said "):
            with self.subTest(text=text):
                self.assertEqual(REGISTRY.attribution_phrase(text), (True, None))

    def test_attribution_phrase_reports_a_trailing_speech_verb(self) -> None:
        self.assertEqual(REGISTRY.attribution_phrase("The reporter stated: "), (True, None))
        self.assertEqual(REGISTRY.attribution_phrase("The exhibit was read: "), (False, None))
        self.assertEqual(REGISTRY.attribution_phrase("The witness said earlier "), (False, None))
        found, mention = REGISTRY.attribution_phrase("The witness answers ")
        self.assertTrue(found)
        self.assertEqual(mention.label if mention else None, "THE WITNESS")

    def test_attribution_takes_last_phrase_before_quote(self) -> None:
        text = "Counsel asked, and the witness answered "
        self.assertEqual(self.label(text), "THE WITNESS")

    def test_turns_follow_labels_and_continuations(self) -> None:
        turns = speaker_turns(SPAN, 12)
        self.assertEqual(
            [(t.label, t.line_start, t.line_end) for t in turns],
            [("EXAMINING COUNSEL", 12, 13), ("THE WITNESS", 14, 14), ("EXAMINING COUNSEL", 17, 17)],
        )
        self.assertEqual(turns[0].text, "So the original never left\nthe records room?")

    def test_quote_inside_one_turn_has_its_speaker(self) -> None:
        turns = speaker_turns(SPAN, 12)
        self.assertEqual(speaker_of("never left the records room", turns), "EXAMINING COUNSEL")
        self.assertEqual(speaker_of("It left once.", turns), "THE WITNESS")
        self.assertIsNone(speaker_of("It left once.", ()))

    def test_quote_spanning_two_turns_has_no_speaker(self) -> None:
        turns = speaker_turns(SPAN, 12)
        self.assertIsNone(speaker_of("records room? It left once.", turns))
        self.assertIsNone(speaker_of("Trailing prose.", turns))

    def test_unregistered_transcript_label_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, kind in (("T0009", "transcript"), ("M0009", "motion")):
                (root / f"{name}.md").write_text(
                    f"---\nid: {name}\ntype: {kind}\ndate: 2025-01-01\n"
                    "designation: public\n---\n\n# Record\n\n"
                    "THE WITNESS: Yes.\nTHE REPORTER: Noted.\n",
                    encoding="utf-8",
                )
            found = unregistered_labels(compile_corpus(root), REGISTRY)
        self.assertEqual(found, (("T0009", 11),))

    def test_reference_corpus_labels_are_registered(self) -> None:
        self.assertEqual(unregistered_labels(compile_corpus(CORPUS_ROOT), REGISTRY), ())


if __name__ == "__main__":
    unittest.main()
