"""Unit tests for researcher_profile.works selection."""

from django.test import SimpleTestCase

from research_ai.services.researcher_profile import works as works_mod
from research_ai.tests.researcher_profile.helpers import oa_work
from utils.openalex import Work


def _works(results, author_id="A123"):
    return [Work.from_openalex(r, author_id=author_id) for r in results]


class SelectWorksTests(SimpleTestCase):
    def test_select_works_dedupes_by_title_and_year(self):
        # Arrange: the same paper twice.
        works = _works(
            [
                oa_work("Same Paper", 2023, "first"),
                oa_work("Same Paper", 2023, "first"),
            ]
        )
        # Act
        selected = works_mod._select_works(works)
        # Assert
        self.assertEqual([w.title for w in selected], ["Same Paper"])

    def test_select_works_prioritizes_first_and_last_author(self):
        # Arrange: eight works; the lead/senior-author papers are the older ones,
        # and one work is undated (sorts last within its tier).
        works = _works(
            [
                oa_work("Middle A", 2025, "middle"),
                oa_work("Middle B", 2024, "middle"),
                oa_work("First Old", 2019, "first"),
                oa_work("Last Older", 2018, "last"),
                oa_work("Middle C", 2022, "middle"),
                oa_work("First New", 2023, "first"),
                oa_work("Middle D", 2021, "middle"),
                oa_work("Middle Undated", None, "middle"),
            ]
        )
        # Act
        selected = works_mod._select_works(works)
        # Assert: every first/last paper kept (newest first), middles fill the rest.
        self.assertEqual(
            [w.title for w in selected],
            ["First New", "First Old", "Last Older", "Middle A", "Middle B"],
        )
