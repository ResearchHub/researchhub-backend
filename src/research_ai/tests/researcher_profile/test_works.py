"""Unit tests for researcher_profile.works (extraction + selection)."""

from django.test import SimpleTestCase

from research_ai.services.researcher_profile import works as works_mod
from research_ai.tests.researcher_profile.helpers import oa_work


class OpenAlexWorksExtractionTests(SimpleTestCase):
    def test_extract_openalex_works_dedupes_and_skips_unusable(self):
        # Arrange: a repeated work and an untitled (unparseable) one.
        results = [
            oa_work("Same Paper", 2023, "first"),
            oa_work("Same Paper", 2023, "first"),
            {"display_name": "", "publication_year": 2023},
        ]
        # Act
        works = works_mod._extract_openalex_works(results, "A123")
        # Assert
        self.assertEqual([w.title for w in works], ["Same Paper"])

    def test_select_works_prioritizes_first_and_last_author(self):
        # Arrange: eight works; the lead/senior-author papers are the older ones,
        # and one work is undated (sorts last within its tier).
        results = [
            oa_work("Middle A", 2025, "middle"),
            oa_work("Middle B", 2024, "middle"),
            oa_work("First Old", 2019, "first"),
            oa_work("Last Older", 2018, "last"),
            oa_work("Middle C", 2022, "middle"),
            oa_work("First New", 2023, "first"),
            oa_work("Middle D", 2021, "middle"),
            oa_work("Middle Undated", None, "middle"),
        ]
        # Act
        works = works_mod._select_works(
            works_mod._extract_openalex_works(results, "A123")
        )
        # Assert: every first/last paper kept (newest first), middles fill the rest.
        self.assertEqual(
            [w.title for w in works],
            ["First New", "First Old", "Last Older", "Middle A", "Middle B"],
        )
