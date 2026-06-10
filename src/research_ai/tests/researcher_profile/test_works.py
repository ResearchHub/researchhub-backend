"""Unit tests for researcher_profile.works (extraction + selection)."""

from django.test import SimpleTestCase

from research_ai.services.researcher_profile import works as works_mod
from research_ai.tests.researcher_profile.helpers import oa_work


class OpenAlexWorksExtractionTests(SimpleTestCase):
    def test_extract_openalex_works_maps_fields_and_author_position(self):
        # Arrange: second work has no DOI and lists this author mid-list by bare id.
        results = [
            oa_work("Lead Paper", 2024, "first"),
            {
                "display_name": "Middle Paper",
                "publication_year": 2023,
                "doi": None,
                "id": "https://openalex.org/W2",
                "authorships": [
                    {
                        "author": {"id": "https://openalex.org/A999"},
                        "author_position": "first",
                    },
                    {"author": {"id": "A123"}, "author_position": "middle"},
                ],
            },
        ]
        # Act
        works = works_mod._extract_openalex_works(results, "https://openalex.org/A123")
        # Assert
        self.assertEqual(works[0]["author_position"], "first")
        self.assertEqual(works[0]["source_url"], "https://doi.org/10.1/lead-paper")
        # Falls back to the OpenAlex work URL when there is no DOI.
        self.assertEqual(works[1]["source_url"], "https://openalex.org/W2")
        self.assertEqual(works[1]["author_position"], "middle")

    def test_extract_openalex_works_dedupes_and_drops_unusable(self):
        # Arrange: a repeated work, an untitled one, and one without any URL.
        results = [
            oa_work("Same Paper", 2023, "first"),
            oa_work("Same Paper", 2023, "first"),
            {"display_name": "", "publication_year": 2023},
            {"display_name": "No URL Paper", "publication_year": 2023, "doi": None},
        ]
        # Act
        works = works_mod._extract_openalex_works(results, "A123")
        # Assert
        self.assertEqual([w["title"] for w in works], ["Same Paper"])

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
            [w["title"] for w in works],
            ["First New", "First Old", "Last Older", "Middle A", "Middle B"],
        )
