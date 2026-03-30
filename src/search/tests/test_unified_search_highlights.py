from unittest import TestCase
from unittest.mock import MagicMock

from search.services.unified_search_service import UnifiedSearchService


class TestExtractDocumentHighlights(TestCase):
    def setUp(self):
        self.service = object.__new__(UnifiedSearchService)

    def test_none_highlights_returns_nones(self):
        result = self.service._extract_document_highlights(None)
        self.assertEqual(result, (None, None))

    def test_empty_highlights_returns_nones(self):
        result = self.service._extract_document_highlights({})
        self.assertEqual(result, (None, None))

    def test_empty_paper_title_list_returns_nones(self):
        class Highlights:
            paper_title = []
        result = self.service._extract_document_highlights(Highlights())
        self.assertEqual(result, (None, None))

    def test_nonempty_paper_title_returns_first(self):
        class Highlights:
            paper_title = ["<mark>test</mark>"]
        result = self.service._extract_document_highlights(Highlights())
        self.assertEqual(result, ("<mark>test</mark>", "title"))

    def test_empty_title_falls_through(self):
        class Highlights:
            title = []
        result = self.service._extract_document_highlights(Highlights())
        self.assertEqual(result, (None, None))

    def test_nonempty_abstract(self):
        class Highlights:
            abstract = ["snippet"]
        result = self.service._extract_document_highlights(Highlights())
        self.assertEqual(result, ("snippet", "abstract"))

    def test_nonempty_renderable_text(self):
        class Highlights:
            renderable_text = ["content snippet"]
        result = self.service._extract_document_highlights(Highlights())
        self.assertEqual(result, ("content snippet", "content"))
