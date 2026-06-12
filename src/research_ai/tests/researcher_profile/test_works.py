"""Unit tests for researcher_profile.works selection."""

from django.test import SimpleTestCase

from research_ai.services.researcher_profile import works as works_mod
from utils.openalex import Work
from utils.tests.openalex_helpers import oa_work


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

    def test_select_works_drops_papers_without_full_text(self):
        # Arrange: a readable paper and a paywalled one with no PDF.
        works = _works(
            [
                oa_work("Readable", 2023, "first"),
                oa_work("No Full Text", 2024, "first", pdf_url=""),
            ]
        )
        # Act
        selected = works_mod._select_works(works)
        # Assert: only the paper we can actually read is kept.
        self.assertEqual([w.title for w in selected], ["Readable"])

    def test_select_works_keeps_most_recent_of_a_duplicate(self):
        # Arrange: the same paper as two records in the same year, the newer one
        # listed second -- ranking by recency, not input order, should keep it.
        older = Work("Dup", "2023-02-01", "2023", "old-url", "first", "old.pdf")
        newer = Work("Dup", "2023-09-01", "2023", "new-url", "first", "new.pdf")
        # Act
        selected = works_mod._select_works([older, newer])
        # Assert: deduped to the most recent version of the paper.
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].source_url, "new-url")

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
