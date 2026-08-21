import unittest

from scripts.legal_matters_offline_backfill import (
    _clean_field,
    choose_email_date,
    merge_candidate_sources,
    normalize_date,
)


class NormalizeDateTests(unittest.TestCase):
    def test_mm_dd_yyyy(self) -> None:
        self.assertEqual(normalize_date("01/15/2024"), "2024-01-15")

    def test_iso(self) -> None:
        self.assertEqual(normalize_date("2024-01-15"), "2024-01-15")

    def test_two_digit_year_low(self) -> None:
        self.assertEqual(normalize_date("3/5/25"), "2025-03-05")

    def test_two_digit_year_high(self) -> None:
        self.assertEqual(normalize_date("3/5/95"), "1995-03-05")

    def test_iso_with_time(self) -> None:
        self.assertEqual(normalize_date("2024-06-15T10:30:00Z"), "2024-06-15")

    def test_invalid_date(self) -> None:
        self.assertIsNone(normalize_date("13/32/2024"))

    def test_empty_string(self) -> None:
        self.assertIsNone(normalize_date(""))

    def test_garbage(self) -> None:
        self.assertIsNone(normalize_date("not-a-date"))

    def test_embedded_whitespace(self) -> None:
        self.assertEqual(normalize_date("  2024-01-15  "), "2024-01-15")

    def test_invalid_month(self) -> None:
        self.assertIsNone(normalize_date("00/15/2024"))


class ChooseEmailDateTests(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertIsNone(choose_email_date([]))

    def test_frequency_wins(self) -> None:
        result = choose_email_date(["2024-01-15", "2024-03-01", "2024-01-15"])
        self.assertEqual(result, "2024-01-15")

    def test_tie_breaks_earliest(self) -> None:
        result = choose_email_date(["2024-06-01", "2024-01-15"])
        self.assertEqual(result, "2024-01-15")

    def test_single(self) -> None:
        self.assertEqual(choose_email_date(["2024-09-01"]), "2024-09-01")


class CleanFieldTests(unittest.TestCase):
    def test_newlines_collapsed(self) -> None:
        self.assertEqual(_clean_field("line1\nline2\nline3"), "line1 line2 line3")

    def test_extra_spaces_collapsed(self) -> None:
        self.assertEqual(_clean_field("a    b     c"), "a b c")

    def test_truncation(self) -> None:
        long = "x" * 250
        result = _clean_field(long)
        self.assertLessEqual(len(result), 200)
        self.assertTrue(result.endswith("\u2026"))
        self.assertEqual(result, "x" * 197 + "\u2026")

    def test_short_unchanged(self) -> None:
        self.assertEqual(_clean_field("hello"), "hello")

    def test_empty(self) -> None:
        self.assertEqual(_clean_field(""), "")

    def test_carriage_return(self) -> None:
        self.assertEqual(_clean_field("a\r\nb"), "a b")


class MergeCandidateSourcesTests(unittest.TestCase):
    def test_merges_email_and_markdown(self) -> None:
        email = {"Case A": ["2024-01-15"], "Case B": ["2024-03-01"]}
        md = {"Case A": ["2024-06-01"], "Case C": ["2024-09-01"]}
        merged = merge_candidate_sources(email, md)
        self.assertEqual(sorted(merged["Case A"]), ["2024-01-15", "2024-06-01"])
        self.assertEqual(merged["Case B"], ["2024-03-01"])
        self.assertEqual(merged["Case C"], ["2024-09-01"])

    def test_no_args_returns_empty(self) -> None:
        merged = merge_candidate_sources()
        self.assertEqual(dict(merged), {})

    def test_single_map_preserved(self) -> None:
        source = {"Case A": ["2024-01-10"]}
        merged = merge_candidate_sources(source)
        self.assertEqual(merged["Case A"], ["2024-01-10"])

    def test_duplicate_dates_across_sources_preserved(self) -> None:
        map1 = {"Case A": ["2024-01-10"]}
        map2 = {"Case A": ["2024-01-10"]}
        merged = merge_candidate_sources(map1, map2)
        self.assertEqual(merged["Case A"], ["2024-01-10", "2024-01-10"])


if __name__ == "__main__":
    unittest.main()
