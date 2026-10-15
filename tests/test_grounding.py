from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from stonewall.attribution import load_speakers
from stonewall.compiler import CompiledCorpus, compile_corpus
from stonewall.disclosure import load_policy
from stonewall.errors import AnswerError, DisclosureError
from stonewall.grounding import AnswerAudit, audit_answer, parse_answer, split_claims
from stonewall.hashing import canonical_json_bytes, sha256_bytes
from stonewall.packet import build_packet
from stonewall.retrieval import query_corpus

CORPUS_ROOT = REPO_ROOT / "examples" / "corpus"
ANSWERS = REPO_ROOT / "examples" / "answers"
POLICY_PATH = REPO_ROOT / "examples" / "disclosure-policy.toml"
QUESTION = "Where was the original binder kept, and did it ever leave?"
CORPUS = compile_corpus(CORPUS_ROOT)
POLICY = load_policy(POLICY_PATH)
SPEAKERS = load_speakers(REPO_ROOT / "examples" / "speakers.toml")
DIGEST = build_packet(CORPUS, POLICY, QUESTION, channel="model", limit=4).digest


REVIEW_DIGEST = build_packet(CORPUS, POLICY, QUESTION, channel="review", limit=4).digest


def answer_text(
    body: str, *, header: str = "", channel: str = "model", digest: str = DIGEST
) -> str:
    return (
        f"---\nquestion: {QUESTION}\nchannel: {channel}\nlimit: 4\npacket: {digest}\n"
        f"{header}---\n\n{body}\n"
    )


def audit(
    body: str, *, release_to: str | None = None, channel: str = "model"
) -> AnswerAudit:
    digest = REVIEW_DIGEST if channel == "review" else DIGEST
    document = parse_answer(answer_text(body, channel=channel, digest=digest), source="answer.md")
    return audit_answer(document, CORPUS, POLICY, SPEAKERS, release_to=release_to)


def outcomes(body: str) -> list[tuple[str, str]]:
    return [(finding.rule, finding.detail) for finding in audit(body).findings]


def rules(body: str) -> tuple[str, ...]:
    return audit(body).rules()


def fixture(
    name: str, corpus: CompiledCorpus = CORPUS, release_to: str | None = None
) -> AnswerAudit:
    text = (ANSWERS / f"{name}.md").read_text(encoding="utf-8")
    document = parse_answer(text, source=f"examples/answers/{name}.md")
    return audit_answer(document, corpus, POLICY, SPEAKERS, release_to=release_to)


def pairs(result: AnswerAudit) -> set[tuple[int, str]]:
    return {(finding.claim, finding.rule) for finding in result.findings}


def corpus_copy(raw: str) -> Path:
    root = Path(raw) / "corpus"
    shutil.copytree(CORPUS_ROOT, root)
    return root


def record(artifact_id: str, designation: str, body: str) -> str:
    return (
        f"---\nid: {artifact_id}\ntype: note\ndate: 2025-01-01\n"
        f"designation: {designation}\n---\n\n{body}\n"
    )


class PacketTests(unittest.TestCase):
    def test_packet_handles_follow_rank_order(self) -> None:
        packet = build_packet(CORPUS, POLICY, QUESTION, channel="model", limit=4)
        rows = [
            (entry.handle, entry.hit.citation.address.split("@")[0], entry.designation)
            for entry in packet.entries
        ]
        self.assertEqual(rows, [
            ("S1", "T0002:12-15", "public"),
            ("S2", "T0002:19-21", "public"),
            ("S3", "T0002:10-10", "public"),
            ("S4", "D0002:12-13", "confidential"),
        ])

    def test_packet_digest_is_sha256_of_canonical_body(self) -> None:
        first = build_packet(CORPUS, POLICY, QUESTION, channel="model", limit=4)
        second = build_packet(CORPUS, POLICY, QUESTION, channel="model", limit=4)
        self.assertEqual(
            canonical_json_bytes(first.to_dict()), canonical_json_bytes(second.to_dict())
        )
        self.assertEqual(first.digest, sha256_bytes(canonical_json_bytes(first.body())))
        self.assertEqual(first.body()["policy"], POLICY.digest)

    def test_packet_carries_no_scores_or_root(self) -> None:
        packet = build_packet(CORPUS, POLICY, QUESTION, channel="review", limit=8)
        raw = canonical_json_bytes(packet.to_dict()).decode("utf-8")
        self.assertNotIn("score", raw)
        self.assertNotIn(str(CORPUS.root), raw)

    def test_packet_text_is_the_verified_span(self) -> None:
        for entry in build_packet(CORPUS, POLICY, QUESTION, channel="model", limit=4).entries:
            digest = sha256_bytes(entry.text.encode("utf-8"))
            self.assertEqual(digest, entry.hit.citation.span_sha256)

    def test_retrieval_outside_the_view_is_refused(self) -> None:
        def unfiltered(_view: CompiledCorpus, question: str, *, limit: int) -> list:
            return query_corpus(CORPUS, question, limit=limit)

        with mock.patch("stonewall.packet.query_corpus", unfiltered), self.assertRaises(
            AnswerError
        ):
            build_packet(CORPUS, POLICY, "weakest link custody chain", channel="model", limit=4)

    def test_packet_limit_bounds(self) -> None:
        for limit in (0, 21):
            with self.assertRaises(AnswerError):
                build_packet(CORPUS, POLICY, QUESTION, channel="model", limit=limit)

    def test_unknown_channel_raises(self) -> None:
        with self.assertRaises(DisclosureError) as caught:
            build_packet(CORPUS, POLICY, QUESTION, channel="nope", limit=4)
        self.assertEqual(caught.exception.rule, "unknown_channel")


class ParsingTests(unittest.TestCase):
    def assert_refused(self, text: str) -> None:
        with self.assertRaises(AnswerError):
            parse_answer(text, source="answer.md")

    def refs(self, body: str) -> list[list[str]]:
        return [[ref.written for ref in claim.refs] for claim in split_claims(body)]

    def test_front_matter_requires_exact_fields(self) -> None:
        self.assert_refused(answer_text("A [S1].").replace(f"packet: {DIGEST}\n", ""))
        self.assert_refused(answer_text("A [S1].", header="author: someone\n"))

    def test_noncanonical_digest_rejected(self) -> None:
        for digest in (DIGEST.upper(), DIGEST[:63], "g" + DIGEST[1:]):
            self.assert_refused(answer_text("A [S1].").replace(DIGEST, digest))

    def test_expect_must_be_sorted_known_rules(self) -> None:
        for expect in ("unknown_handle uncited_claim", "uncited_claim uncited_claim", "made_up"):
            self.assert_refused(answer_text("A [S1].", header=f"expect: {expect}\n"))
        document = parse_answer(answer_text("A.", header="expect: uncited_claim\n"), source="a")
        self.assertEqual(document.expect, ("uncited_claim",))

    def test_trailing_refs_attach_to_previous_sentence(self) -> None:
        self.assertEqual(
            self.refs('One "two." [S1] Three. [S2] [S3] Four [S4].'),
            [["S1"], ["S2", "S3"], ["S4"]],
        )
        self.assertEqual(self.refs('One "two." [S1]. Three [S2].'), [["S1"], ["S2"]])

    def test_terminal_mark_inside_closing_quote_ends_sentence(self) -> None:
        claims = split_claims('He answered \u201cIt left once.\u201d Then "more?" Done [S1].')
        self.assertEqual(
            [claim.text for claim in claims],
            ["He answered \u201cIt left once.\u201d", 'Then "more?"', "Done [S1]."],
        )

    def test_decimal_point_does_not_split(self) -> None:
        claims = split_claims("It weighed 1.5 pounds and cost 3.25 [S1].")
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].figures, ("1.5", "3.25"))

    def test_headings_and_list_markers_are_not_claims(self) -> None:
        claims = split_claims(
            "# Summary\n\n- First point [S1].\n* Second point [S2].\n"
            "1. Third point [S3].\n12) Fourth point [S4].\n## End"
        )
        texts = [claim.text for claim in claims]
        self.assertEqual(
            texts,
            ["First point [S1].", "Second point [S2].", "Third point [S3].", "Fourth point [S4]."],
        )
        self.assertEqual([claim.figures for claim in claims], [(), (), (), ()])

    def test_numbered_list_items_are_audited_without_markers(self) -> None:
        result = audit("1. The witness signed it out on March 3 [S1].\n"
                       "2) The witness compared all 42 pages [S2].")
        self.assertEqual(result.findings, ())
        self.assertEqual([(p.line, p.column) for p in result.claims], [(8, 4), (9, 4)])

    def test_hash_line_that_is_not_a_heading_is_audited(self) -> None:
        self.assertEqual([c.text for c in split_claims("#99 pages were missing")],
                         ["#99 pages were missing"])
        self.assertEqual(rules("#99 pages were missing"), ("uncited_claim",))

    def test_heading_with_a_figure_or_quotation_is_a_claim(self) -> None:
        claims = split_claims('## On March 9 "it vanished"\n\nBody [S1].')
        self.assertEqual([c.text for c in claims], ['On March 9 "it vanished"', "Body [S1]."])
        self.assertEqual(rules('## On March 9 "it vanished"'), ("uncited_claim",))
        self.assertEqual(rules("## Custody"), ("empty_answer",))

    def test_sentence_ends_after_closing_emphasis_and_footnotes(self) -> None:
        tail = "The witness signed it out on March 3 [S1]."
        for lead in ("**The binder burned.**", "_The binder burned._",
                     "(The binder burned.)", "The binder burned.[^1]",
                     "He wrote 'the binder burned.'", "The binder burned.)**",
                     "~~The binder burned.~~", "`The binder burned.`",
                     "<b>The binder burned.</b>", "[The binder burned.]",
                     "The binder burned\u3002", "The binder burned\uff0e"):
            with self.subTest(lead=lead):
                claims = split_claims(f"{lead} {tail}")
                self.assertEqual([c.text for c in claims], [lead, tail])
                self.assertEqual(rules(f"{lead} {tail}"), ("uncited_claim",))

    def test_mark_run_together_with_the_next_word_does_not_end_a_sentence(self) -> None:
        self.assertEqual(len(split_claims("The binder burned.The witness signed it [S1].")), 1)

    def test_numbered_line_inside_a_paragraph_is_text(self) -> None:
        body = ("The witness signed it out on March 3 [S1].\n"
                "99) pages were missing when the binder came back [S2].")
        self.assertEqual([c.text for c in split_claims(body)][1],
                         "99) pages were missing when the binder came back [S2].")
        self.assertEqual(pairs(audit(body)), {(2, "unsupported_figure")})
        self.assertEqual(len(split_claims("- First [S1].\n2) Second [S2].")), 2)

    def test_ref_grammar(self) -> None:
        self.assertEqual(self.refs("A [S1]. B [S1, S3]. C [D0001:12-13]. D [D0001:12]."),
                         [["S1"], ["S1", "S3"], ["D0001:12-13"], ["D0001:12"]])
        ref = split_claims("D [D0001:12].")[0].refs[0]
        self.assertEqual((ref.artifact_id, ref.line_start, ref.line_end), ("D0001", 12, 12))

    def test_malformed_refs(self) -> None:
        for bracket in ("[S0]", "[S01]", "[S21]", "[D0001:13-12]", "[D0001:0-2]", "[S1;S2]",
                        "[D0001]", "[D0001:12-13@abc123def456]"):
            result = audit(f"The original binder was kept in the records room {bracket}.")
            self.assertEqual(result.rules(), ("malformed_citation", "uncited_claim"), bracket)
            self.assertEqual([f.ref for f in result.findings], ["", ""], bracket)
        self.assertIn("item 2", audit("Kept in the records room [S1, S0].").render_text())

    def test_non_citation_brackets_ignored(self) -> None:
        result = audit("The binder was kept [sic] in the records room [emphasis added] [S1].")
        self.assertEqual(result.findings, ())

    def test_markdown_link_to_handle_is_a_citation(self) -> None:
        self.assertEqual(self.refs("The records room [S1](x-5)."), [["S1"]])
        self.assertEqual(rules("The records room [S1](x-5)."), ())

    def test_link_to_privileged_handle_reaches_the_release_check(self) -> None:
        result = audit("The copy is the weak link [S1] [S2](#s2).", channel="review",
                       release_to="publish")
        self.assertEqual([(f.claim, f.rule, f.ref) for f in result.findings],
                         [(1, "designation_exceeds_channel", "S2")])

    def test_link_target_with_spaces_or_quotes_is_audited_text(self) -> None:
        for body in (
            (
                "The witness signed it out on March 3 [S1](and destroyed it on March 13,"
                ' saying "I burned it").'
            ),
            (
                "The witness signed it out on March 3 [S1](. The witness then destroyed the"
                ' binder on March 13 and said "I burned it") and returned it on March 5 [S1].'
            ),
        ):
            with self.subTest(body=body):
                result = audit(body)
                self.assertFalse(result.grounded)
                self.assertEqual(result.rules(), ("unsupported_figure", "unsupported_quote"))

    def test_quotation_inside_plain_bracket_is_checked(self) -> None:
        body = 'The witness testified [that "I never let the original leave"] [S1].'
        self.assertEqual(rules(body), ("unsupported_quote",))

    def test_figure_inside_plain_bracket_is_checked(self) -> None:
        body = "The witness compared [all 99] pages before the binder went back [S2]."
        self.assertEqual(rules(body), ("unsupported_figure",))

    def test_citation_bracket_with_extra_words_is_malformed(self) -> None:
        for bracket in ("[see P0001:12-13]", "[see D0001:12-13]", "[cf. S2]"):
            with self.subTest(bracket=bracket):
                body = f"The copy is the weak link [S1] {bracket}."
                self.assertEqual(rules(body), ("malformed_citation",))

    def test_long_footnote_label_is_audited_text(self) -> None:
        body = "The witness signed it out on March 3 [S1][^destroyed_on_March_13]."
        self.assertEqual(rules(body), ("unsupported_figure",))
        self.assertEqual(rules("The witness signed it out on March 3 [S1][^n13]."), ())

    def test_miscased_ref_is_malformed(self) -> None:
        for bracket in ("[s9]", "[s1]", "[t0002:14-14]"):
            with self.subTest(bracket=bracket):
                body = f"The binder was destroyed in a fire {bracket}."
                self.assertEqual(rules(body), ("malformed_citation", "uncited_claim"))

    def test_nested_citation_bracket_is_malformed(self) -> None:
        self.assertEqual(self.refs("The records room [S1 [S2]]."), [[]])
        self.assertEqual(rules("The records room [S1 [S2]]."),
                         ("malformed_citation", "uncited_claim"))

    def test_handle_bound_follows_packet_limit(self) -> None:
        self.assertEqual(self.refs("A [S20]. B [S21]."), [["S20"], []])
        with mock.patch("stonewall.grounding.MAX_PACKET_LIMIT", 25):
            self.assertEqual(self.refs("B [S21]."), [["S21"]])

    def test_brackets_inside_quotation_are_quoted_text(self) -> None:
        claim = split_claims('He wrote "see [S1] here" [S2].')[0]
        self.assertEqual([ref.written for ref in claim.refs], ["S2"])
        self.assertEqual(claim.quotations[0].text, "see [S1] here")


class AuditTests(unittest.TestCase):
    def test_grounded_fixture_is_clean(self) -> None:
        result = fixture("grounded")
        self.assertTrue(result.ok)
        self.assertEqual(result.findings, ())
        self.assertEqual([p.kind for p in result.claims],
                         ["statement", "quotation", "figure", "quotation", "statement"])
        self.assertEqual(
            [p.backed_by for p in result.claims], [("S1",), ("S1",), ("S1",), ("S2",), ("S4",)]
        )
        self.assertEqual([p.speakers for p in result.claims],
                         [(), ("THE WITNESS",), (), ("THE WITNESS",), ()])
        self.assertEqual(result.claims[2].figures, 2)

    def test_fabricated_fixture_findings_are_pinned(self) -> None:
        result = fixture("fabricated")
        self.assertEqual(sorted(pairs(result)), [
            (1, "uncited_claim"), (2, "quote_wrong_speaker"), (3, "unsupported_figure"),
            (4, "quote_wrong_source"), (5, "unsupported_quote"), (6, "unknown_artifact"),
            (7, "not_retrieved"), (8, "unknown_handle"),
        ])
        self.assertEqual(len(result.findings), 8)
        details = {f.claim: f.detail for f in result.findings}
        self.assertEqual(details[2], "said by EXAMINING COUNSEL")
        self.assertEqual(details[4], "found in S2")
        self.assertFalse(result.grounded)
        self.assertTrue(result.releasable)

    def test_grounded_answer_not_releasable_to_publish(self) -> None:
        result = fixture("grounded", release_to="publish")
        self.assertTrue(result.grounded)
        self.assertFalse(result.releasable)
        self.assertEqual(
            [(f.claim, f.rule, f.ref, f.detail) for f in result.findings],
            [(5, "designation_exceeds_channel", "S4", "confidential exceeds publish")],
        )
        self.assertIn("NOT RELEASABLE to publish", result.render_text())

    def test_narrower_range_inside_returned_span_is_backed(self) -> None:
        result = audit('Counsel asked "So the original never left the records room?" '
                       "[T0002:14-14].")
        self.assertEqual(result.findings, ())
        self.assertEqual(result.claims[0].backed_by, ("S1",))

    def test_wider_range_is_not_retrieved(self) -> None:
        self.assertEqual(rules("It left once [T0002:12-16]."), ("not_retrieved",))

    def test_quote_outside_narrowed_range_is_wrong_source(self) -> None:
        result = audit('The witness said "I compared all 42 pages" [T0002:19-19].')
        found = [(f.rule, f.detail) for f in result.findings]
        self.assertEqual(found, [("quote_wrong_source", "found in S2")])

    def test_figure_outside_narrowed_range_is_unsupported(self) -> None:
        self.assertEqual(rules("It returned on March 5 [T0002:14-14]."), ("unsupported_figure",))
        self.assertEqual(rules("It returned on March 5 [T0002:15-15]."), ())

    def test_quotation_case_and_punctuation_are_significant(self) -> None:
        for quote in ("it left once", "It left once!"):
            self.assertEqual(rules(f'The record says "{quote}" [S1].'), ("unsupported_quote",))

    def test_quotation_truncating_a_number_fails(self) -> None:
        self.assertEqual(rules('The record says "compared all 4" [S2].'), ("unsupported_quote",))

    def test_ellipsis_fragments_must_appear_in_order(self) -> None:
        self.assertEqual(rules('The record reads "It left once ... March 5" [S1].'), ())
        reversed_order = rules('The record reads "March 5 ... It left once" [S1].')
        self.assertEqual(reversed_order, ("unsupported_quote",))

    def test_ellipsis_splice_across_turns_is_unsupported(self) -> None:
        body = 'The record reads "In the records room ... the original never left" [S1].'
        self.assertEqual(outcomes(body), [("unsupported_quote", "spans turns")])

    def test_figure_matching_is_word_bounded(self) -> None:
        self.assertEqual(rules("It went out on March 3 [S1]."), ())
        for figure in ("13", "33", "3.5", "-3"):
            found = rules(f"It went out on March {figure} [S1].")
            self.assertEqual(found, ("unsupported_figure",), figure)

    def test_figure_qualifiers_are_compared(self) -> None:
        for body in ("It went out on March 3rd [S1].", "It went out on the 5th [S1]."):
            self.assertEqual(rules(body), (), body)
        for body in ("It returned on April 5 [S1].", "It cost $5 million [S1]."):
            self.assertEqual(rules(body), ("unsupported_figure",), body)

    def test_month_forms_are_compared(self) -> None:
        # 'Sept. 5' ends a sentence at its period; text-level tests cover it.
        for figure in ("5 April", "april 5", "Sept 5", "April **5**", "April&nbsp;5"):
            with self.subTest(figure=figure):
                self.assertEqual(rules(f"It returned on {figure} [S1]."), ("unsupported_figure",))
        for figure in ("5 March", "March 5th", "the 5th of march"):
            with self.subTest(figure=figure):
                self.assertEqual(rules(f"It returned on {figure} [S1]."), ())

    def test_figures_inside_quotations_and_refs_are_not_figures(self) -> None:
        claim = split_claims('The record "has 99 pages" here [T0002:19-21].')[0]
        self.assertEqual(claim.figures, ())

    def test_unbalanced_quotation(self) -> None:
        result = audit('The witness answered [S1] "It left once.')
        self.assertEqual(result.rules(), ("unbalanced_quotation",))
        self.assertEqual(split_claims('A [S1] "open.')[0].quotations, ())

    def test_empty_answer(self) -> None:
        result = audit("# Only a heading")
        found = [(f.line, f.column, f.claim, f.rule) for f in result.findings]
        self.assertEqual(found, [(8, 1, 0, "empty_answer")])
        self.assertFalse(result.ok)

    def test_privileged_id_behaves_like_unknown_artifact(self) -> None:
        self.assertEqual(rules("The copy is the weak link [P0001:12-13]."), ("unknown_artifact",))
        self.assertEqual(rules("An invented reference [Z0001:12-13]."), ("unknown_artifact",))

    def test_packet_mismatch_reported_and_claims_still_audited(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = corpus_copy(raw)
            path = root / "transcripts" / "T0002_custody.md"
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace("March 5.", "March 6."), encoding="utf-8")
            result = fixture("grounded", compile_corpus(root))
        self.assertEqual(pairs(result), {(0, "packet_mismatch"), (3, "unsupported_figure")})
        self.assertEqual(result.findings[0].line, 5)

    def test_report_never_contains_answer_content(self) -> None:
        result = audit('The witness said "zephyr quorum lantern" on day 987654 [S1].')
        self.assertEqual(result.rules(), ("unsupported_figure", "unsupported_quote"))
        for output in (result.render_text(), json.dumps(result.to_dict())):
            self.assertNotIn("zephyr", output)
            self.assertNotIn("987654", output)

    def test_defending_counsel_objection_is_proven(self) -> None:
        for name in ("Defending counsel", "Defense counsel"):
            result = audit(f'{name} stated "Objection to form." [S2]')
            self.assertEqual(result.findings, (), name)
            self.assertEqual(result.claims[0].speakers, ("DEFENDING COUNSEL",))

    def test_present_tense_speech_verb_binds(self) -> None:
        result = audit('The witness testifies that "It left once." [S1].')
        self.assertEqual(result.claims[0].speakers, ("THE WITNESS",))
        body = 'The witness testifies that "So the original never left the records room?" [S1].'
        self.assertEqual(outcomes(body), [("quote_wrong_speaker", "said by EXAMINING COUNSEL")])

    def test_interrupting_clause_leaves_speaker_unidentified(self) -> None:
        body = ('The witness, when counsel asked, testified that '
                '"So the original never left the records room?" [S1].')
        self.assertEqual(outcomes(body), [("quote_wrong_speaker", "speaker not identified")])

    def test_last_speech_verb_binds_across_a_non_speech_verb(self) -> None:
        # 'read' is not a speech verb, so 'answered' is the last one and binds
        # the witness, although the exhibit is what was read.
        body = ('The witness answered earlier, then the exhibit was read: '
                '"So the original never left the records room?" [S1]')
        self.assertEqual(outcomes(body), [("quote_wrong_speaker", "said by EXAMINING COUNSEL")])

    def test_speech_verb_lead_ins_bind_the_named_speaker(self) -> None:
        quote = '"So the original never left the records room?" [S1].'
        for lead in ("The witness testified as follows:", "The witness said, in substance,",
                     "The witness testified under oath that", "The witness answered \u2014",
                     "**The witness testified:**", "The witness *testified*",
                     "The witness testified [in part]", "The witness testified (in part)",
                     "The witness answered: **"):
            with self.subTest(lead=lead):
                self.assertEqual(outcomes(f"{lead} {quote}"),
                                 [("quote_wrong_speaker", "said by EXAMINING COUNSEL")])
        self.assertEqual(outcomes(f"The witness testified that\u2014{quote}"),
                         [("quote_wrong_speaker", "said by EXAMINING COUNSEL")])

    def test_lead_in_without_a_speech_verb_is_not_speaker_checked(self) -> None:
        for lead in ("According to the witness,", "The witness put it this way:"):
            with self.subTest(lead=lead):
                body = f'{lead} "So the original never left the records room?" [S1].'
                self.assertEqual(outcomes(body), [])

    def test_unregistered_or_possessive_speaker_on_a_transcript_fails(self) -> None:
        possessive = (
            "The witness's counsel said "
            '"Did anyone compare the copy against the original?" [S2].'
        )
        for body in ('The reporter stated "It left once." [S1].', possessive):
            with self.subTest(body=body):
                self.assertEqual(outcomes(body),
                                 [("quote_wrong_speaker", "speaker not identified")])

    def test_unregistered_speaker_on_a_document_is_not_checked(self) -> None:
        body = 'The order stated "Confirm how the witness received" [S4].'
        self.assertEqual(outcomes(body), [])

    def test_any_cited_span_with_the_speaker_proves_the_quotation(self) -> None:
        body = 'The witness said "the records room" [T0002:14-14, T0002:13-13].'
        self.assertEqual(outcomes(body), [])
        self.assertEqual(audit(body).claims[0].speakers, ("THE WITNESS",))
        wrong = 'The witness said "the records room" [T0002:14-14].'
        self.assertEqual(outcomes(wrong), [("quote_wrong_speaker", "said by EXAMINING COUNSEL")])

    def test_recognized_quotation_pairs_are_checked(self) -> None:
        for open_, close in (("\u2018", "\u2019"), ("\u00ab", "\u00bb"), ("\uff02", "\uff02"),
                             ("\u201c", "\u201d")):
            with self.subTest(mark=open_):
                body = f"The witness testified that {open_}it burned{close} [S1]."
                self.assertEqual(rules(body), ("unsupported_quote",))

    def test_apostrophe_does_not_close_a_single_quotation(self) -> None:
        claim = split_claims("He said \u2018it\u2019s here\u2019 [S1].")[0]
        self.assertEqual([q.text for q in claim.quotations], ["it\u2019s here"])
        self.assertEqual(rules("The custodian\u2019s desk held a copy [S1]."), ())

    def test_unpaired_quotation_punctuation_is_unbalanced(self) -> None:
        for body in ("The witness testified that \u201dit burned\u201d [S1].",
                     "The witness testified that \u00bbit burned [S1].",
                     "The witness testified that \u2019it burned [S1].",
                     "The witness testified that \u300cit burned\u300d [S1].",
                     "The witness testified that \u300eit burned\u300f [S1].",
                     "The witness testified that \u275dit burned\u275e [S1].",
                     "The witness testified that &quot;it burned&quot; [S1]."):
            with self.subTest(body=body):
                self.assertEqual(rules(body), ("unbalanced_quotation",))

    def test_closing_single_mark_after_a_letter_or_before_a_digit_is_an_apostrophe(
        self,
    ) -> None:
        for body in ("The witnesses\u2019 binder was kept in the records room [S1].",
                     "The binder dates from the \u201990s [S1]."):
            with self.subTest(body=body):
                self.assertIsNone(split_claims(body)[0].unbalanced)
        self.assertEqual(rules("The witnesses\u2019 binder was kept in the records room [S1]."),
                         ())

    def test_ascii_single_quotes_are_not_quotation_marks(self) -> None:
        result = audit("The witness testified that 'it burned' [S1].")
        self.assertEqual(result.findings, ())
        self.assertEqual(result.claims[0].kind, "statement")

    def test_block_quote_is_one_quotation(self) -> None:
        fabricated = "The witness testified as follows [S1]:\n\n> I never let it leave. [S1]"
        self.assertEqual(pairs(audit(fabricated)), {(2, "unsupported_quote")})
        true = "> It left once. I signed it out\n> on March 3 [S1]."
        result = audit(true)
        self.assertEqual(result.findings, ())
        self.assertEqual(result.claims[0].kind, "quotation")
        self.assertEqual(rules("> It left once."), ("uncited_claim",))

    def test_block_quote_without_a_colon_lead_in_has_no_speaker_check(self) -> None:
        quote = "> So the original never left the records room? [S1]"
        for body in (quote, f"The witness answered [S1].\n\n{quote}"):
            with self.subTest(body=body):
                result = audit(body)
                self.assertEqual(result.findings, ())
                self.assertEqual(result.claims[-1].speakers, ())

    def test_block_quote_takes_a_colon_lead_in(self) -> None:
        body = ("The witness answered [S1]:\n\n"
                "> So the original never left the records room?\n> [S1]")
        self.assertEqual(pairs(audit(body)), {(2, "quote_wrong_speaker")})
        self.assertEqual(outcomes(body), [("quote_wrong_speaker", "said by EXAMINING COUNSEL")])
        proven = audit("The witness answered: [S1]\n\n> It left once. [S1]")
        self.assertEqual(proven.findings, ())
        self.assertEqual(proven.claims[1].speakers, ("THE WITNESS",))

    def test_release_follows_the_declared_packet(self) -> None:
        body = "The binder stayed in the records room [S1]."
        self.assertTrue(audit(body, channel="review").ok)
        result = audit(body, channel="review", release_to="publish")
        self.assertTrue(result.grounded)
        self.assertFalse(result.releasable)
        self.assertEqual(
            [(f.line, f.column, f.claim, f.rule, f.detail) for f in result.findings],
            [(5, 1, 0, "designation_exceeds_channel", "packet privileged exceeds publish")],
        )
        self.assertIn("NOT RELEASABLE to publish", result.render_text())

    def test_answer_cannot_smuggle_refs_inside_quotes(self) -> None:
        self.assertEqual(rules('"see [S1]"'), ("uncited_claim",))


class NonInterferenceTests(unittest.TestCase):
    def model_packet(self, root: Path) -> bytes:
        packet = build_packet(compile_corpus(root), POLICY, QUESTION, channel="model", limit=4)
        return canonical_json_bytes(packet.to_dict())

    def test_model_packet_is_independent_of_privileged_records(self) -> None:
        reference = self.model_packet(CORPUS_ROOT)
        with tempfile.TemporaryDirectory() as raw:
            root = corpus_copy(raw)
            shutil.rmtree(root / "privileged")
            self.assertEqual(self.model_packet(root), reference)
        with tempfile.TemporaryDirectory() as raw:
            root = corpus_copy(raw)
            terms = " ".join([QUESTION.rstrip("?")] * 6)
            (root / "privileged" / "P0001_custody_advice.md").write_text(
                record("P0001", "privileged", f"# {QUESTION}\n\n{terms}."), encoding="utf-8"
            )
            self.assertEqual(self.model_packet(root), reference)

    def test_privileged_record_cannot_reorder_model_packet(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "corpus"
            note = "# Filing Note\n\nThe {} exhibit was logged with the clerk."
            for name, designation, body in (
                ("public/A0001_alpha", "public", note.format("alpha")),
                ("public/B0001_beta", "public", note.format("beta")),
                ("privileged/P0001_advice", "privileged", "# Advice\n\nAlpha alpha alpha."),
            ):
                path = root / f"{name}.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(record(path.stem[:5], designation, body), encoding="utf-8")
            policy_path = Path(raw) / "policy.toml"
            policy_path.write_text(POLICY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
            policy = load_policy(policy_path)
            question = "alpha beta exhibit"
            packet = build_packet(compile_corpus(root), policy, question, channel="model", limit=2)
            self.assertEqual([e.hit.citation.address.split("@")[0] for e in packet.entries],
                             ["A0001:10-10", "B0001:10-10"])
            shutil.rmtree(root / "privileged")
            reduced = compile_corpus(root)
            without = build_packet(reduced, policy, question, channel="model", limit=2)
            self.assertEqual(
                canonical_json_bytes(packet.to_dict()), canonical_json_bytes(without.to_dict())
            )

    def test_audit_is_independent_of_privileged_records(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = corpus_copy(raw)
            shutil.rmtree(root / "privileged")
            for name in ("grounded", "fabricated"):
                reduced = fixture(name, compile_corpus(root)).to_dict()
                self.assertEqual(reduced, fixture(name).to_dict())


if __name__ == "__main__":
    unittest.main()
