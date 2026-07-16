"""Unit tests for the shared proposal DOI helpers (no Django, no network)."""

import unittest

from research_ai.services.proposal_draft.tools.doi import doi_url, strip_doi_prefix


class DoiUrlTests(unittest.TestCase):
    def test_bare_doi_gets_doi_org_prefix(self):
        # Arrange / Act / Assert: casing is preserved for display.
        self.assertEqual(doi_url("10.1/ABC"), "https://doi.org/10.1/ABC")

    def test_existing_url_passes_through_untouched(self):
        # Arrange / Act / Assert
        cases = (
            "https://doi.org/10.1/a",
            "http://doi.org/10.2/x",  # NOSONAR - test input, not a request
            "https://example.org/paper.pdf",
        )
        for value in cases:
            with self.subTest(value=value):
                self.assertEqual(doi_url(value), value)

    def test_empty_and_none_return_empty(self):
        # Arrange / Act / Assert
        self.assertEqual(doi_url(""), "")
        self.assertEqual(doi_url(None), "")


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
