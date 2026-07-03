"""Unit tests for the shared proposal DOI helper (no Django, no network)."""

import unittest

from research_ai.services.proposal_tools.doi import strip_doi_prefix


class StripDoiPrefixTests(unittest.TestCase):
    def test_strips_known_prefixes_and_lowercases(self):
        # Arrange / Act / Assert
        cases = {
            "https://doi.org/10.1/ABC": "10.1/abc",
            "http://doi.org/10.2/x": "10.2/x",  # NOSONAR - test input, not a request
            "https://dx.doi.org/10.3/y": "10.3/y",
            "doi:10.4/z": "10.4/z",
            "10.5/bare": "10.5/bare",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(strip_doi_prefix(value), expected)

    def test_non_doi_string_returned_unchanged(self):
        # Arrange / Act / Assert: no prefix matched -> bare lowercased string.
        self.assertEqual(
            strip_doi_prefix("https://openalex.org/W1"), "https://openalex.org/w1"
        )

    def test_empty_and_none_return_empty(self):
        # Arrange / Act / Assert
        self.assertEqual(strip_doi_prefix(""), "")
        self.assertEqual(strip_doi_prefix(None), "")
