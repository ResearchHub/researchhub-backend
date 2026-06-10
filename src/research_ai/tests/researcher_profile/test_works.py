"""Unit tests for researcher_profile.works (extraction + selection)."""

from django.test import SimpleTestCase

from research_ai.services.researcher_profile import works as works_mod
from research_ai.tests.researcher_profile.helpers import oa_work, orcid_work


class OrcidWorksExtractionTests(SimpleTestCase):
    def test_extract_orcid_works_prefers_doi_url(self):
        # Arrange
        works_json = {
            "group": [
                {
                    "work-summary": [
                        {
                            "title": {"title": {"value": "A Paper"}},
                            "publication-date": {"year": {"value": "2021"}},
                            "external-ids": {
                                "external-id": [
                                    {
                                        "external-id-type": "doi",
                                        "external-id-value": "10.1/abc",
                                    }
                                ]
                            },
                        },
                        {
                            "title": {"title": {"value": "No Source Paper"}},
                        },
                    ]
                }
            ]
        }
        # Act
        works = works_mod._extract_orcid_works(works_json, "https://orcid.org/0000")
        # Assert
        self.assertEqual(len(works), 2)
        self.assertEqual(works[0]["source_url"], "https://doi.org/10.1/abc")
        self.assertEqual(works[0]["year"], "2021")
        # Falls back to the ORCID record URL when a work has no DOI/url.
        self.assertEqual(works[1]["source_url"], "https://orcid.org/0000")

    def test_extract_orcid_works_drops_when_no_url_available(self):
        # Arrange
        works_json = {"group": [{"work-summary": [{"title": {"value": "X"}}]}]}
        # Act
        works = works_mod._extract_orcid_works(works_json, None)
        # Assert
        self.assertEqual(works, [])

    def test_extract_orcid_works_keeps_most_recent_five(self):
        # Arrange: seven works in ORCID payload order, years shuffled, one undated.
        years = ["2018", "2024", None, "2020", "2025", "2019", "2022"]
        works_json = {
            "group": [
                {"work-summary": [orcid_work(f"Paper {i}", year=year)]}
                for i, year in enumerate(years)
            ]
        }
        # Act
        works = works_mod._extract_orcid_works(works_json, "https://orcid.org/0000")
        # Assert: the five newest, most recent first; undated and oldest dropped.
        self.assertEqual(
            [w["year"] for w in works], ["2025", "2024", "2022", "2020", "2019"]
        )

    def test_extract_orcid_works_dedupes_same_work_across_sources(self):
        # Arrange: one group claiming the same work from two sources.
        works_json = {
            "group": [
                {
                    "work-summary": [
                        orcid_work("Same Paper", year="2023"),
                        orcid_work("Same Paper", year="2023"),
                    ]
                }
            ]
        }
        # Act
        works = works_mod._extract_orcid_works(works_json, "https://orcid.org/0000")
        # Assert
        self.assertEqual(len(works), 1)


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

    def test_select_works_prioritizes_first_and_last_author(self):
        # Arrange: seven works; the lead/senior-author papers are the older ones.
        results = [
            oa_work("Middle A", 2025, "middle"),
            oa_work("Middle B", 2024, "middle"),
            oa_work("First Old", 2019, "first"),
            oa_work("Last Older", 2018, "last"),
            oa_work("Middle C", 2022, "middle"),
            oa_work("First New", 2023, "first"),
            oa_work("Middle D", 2021, "middle"),
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
