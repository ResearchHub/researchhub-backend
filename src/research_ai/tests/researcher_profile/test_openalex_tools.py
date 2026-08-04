"""Unit tests for the OpenAlex tool layer (core Tools, grounding, dispatch)."""

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from research_ai.services.researcher_profile.openalex_tools import (
    SUBMIT_PROFILE,
    OpenAlexToolset,
)
from utils.openalex import Work
from utils.tests.openalex_helpers import create_oa_author_record, create_oa_work


class ToolBuildTests(SimpleTestCase):
    def test_exposes_openalex_tools_and_submit(self):
        # Arrange / Act
        tools = OpenAlexToolset(client=MagicMock()).build_tools()
        names = {tool.name for tool in tools}
        # Assert
        self.assertEqual(
            names,
            {
                "search_institutions",
                "search_authors",
                "get_author",
                "get_author_works",
                "get_work_fulltext",
                SUBMIT_PROFILE,
            },
        )

    def test_submit_profile_is_the_only_terminal_tool(self):
        # Arrange / Act
        terminal = {
            tool.name
            for tool in OpenAlexToolset(client=MagicMock()).build_tools()
            if tool.is_terminal
        }
        # Assert
        self.assertEqual(terminal, {SUBMIT_PROFILE})


class DispatchTests(SimpleTestCase):
    def test_search_authors_returns_compact_candidate_views(self):
        # Arrange
        client = MagicMock()
        client.search_authors_via_name.return_value = {
            "results": [create_oa_author_record()]
        }
        toolset = OpenAlexToolset(client=client).as_toolset()
        # Act
        result, stop = toolset.dispatch("search_authors", {"name": "Jane Doe"})
        # Assert
        self.assertFalse(stop)
        candidate = result["results"][0]
        self.assertEqual(candidate["openalex_author_id"], "https://openalex.org/A123")
        self.assertEqual(candidate["institutions"], ["Stanford University"])
        self.assertIn("Genomics", candidate["top_topics"])

    def test_get_author_works_records_work_provenance(self):
        # Arrange
        client = MagicMock()
        client.get_works_typed.return_value = [
            Work.from_openalex(
                create_oa_work("Lead Paper", 2024, "first"), author_id=None
            )
        ]
        provider = OpenAlexToolset(client=client)
        toolset = provider.as_toolset()
        # Act
        result, _ = toolset.dispatch(
            "get_author_works", {"openalex_author_id": "https://openalex.org/A123"}
        )
        # Assert: the full ground-truth record is kept, keyed by source_url.
        url = result["works"][0]["source_url"]
        self.assertIn(url, provider.returned_works)
        self.assertEqual(provider.returned_works[url]["title"], "Lead Paper")

    def test_submit_profile_captures_input_and_stops(self):
        # Arrange
        provider = OpenAlexToolset(client=MagicMock())
        toolset = provider.as_toolset()
        payload = {"resolution": {"openalex_author_id": "A1", "confidence": 0.9}}
        # Act
        result, stop = toolset.dispatch(SUBMIT_PROFILE, payload)
        # Assert
        self.assertTrue(stop)
        self.assertTrue(result["received"])
        self.assertEqual(provider.submitted, payload)

    def test_tool_failure_is_returned_not_raised(self):
        # Arrange
        client = MagicMock()
        client.search_authors_via_name.side_effect = RuntimeError("oa down")
        toolset = OpenAlexToolset(client=client).as_toolset()
        # Act
        result, stop = toolset.dispatch("search_authors", {"name": "Jane"})
        # Assert
        self.assertFalse(stop)
        self.assertIn("oa down", result["error"])


class GetWorkFulltextTests(SimpleTestCase):
    def _toolset_with_work(self, **kwargs):
        """A toolset that has already returned one work (so it can be read)."""
        client = MagicMock()
        client.get_works_typed.return_value = [
            Work.from_openalex(
                create_oa_work("Lead Paper", 2024, "first"), author_id=None
            )
        ]
        provider = OpenAlexToolset(client=client, **kwargs)
        toolset = provider.as_toolset()
        result, _ = toolset.dispatch(
            "get_author_works", {"openalex_author_id": "https://openalex.org/A123"}
        )
        return provider, toolset, result["works"][0]["source_url"]

    def test_reads_pdf_text_for_returned_work(self):
        # Arrange: a stub fetcher stands in for the PDF download/extract.
        _, toolset, url = self._toolset_with_work(
            pdf_text_fetcher=lambda pdf_url: "METHODS: single-cell RNA-seq on ..."
        )
        # Act
        result, stop = toolset.dispatch("get_work_fulltext", {"source_url": url})
        # Assert
        self.assertFalse(stop)
        self.assertEqual(result["content_type"], "pdf")
        self.assertIn("single-cell", result["text"])

    def test_falls_back_to_abstract_when_no_pdf_text(self):
        # Arrange: the fetcher yields nothing, so the abstract is used.
        _, toolset, url = self._toolset_with_work(pdf_text_fetcher=lambda pdf_url: "")
        # Act
        result, _ = toolset.dispatch("get_work_fulltext", {"source_url": url})
        # Assert
        self.assertEqual(result["content_type"], "abstract")
        self.assertEqual(result["text"], "Abstract text")

    def test_unknown_source_url_errors(self):
        # Arrange
        _, toolset, _ = self._toolset_with_work(pdf_text_fetcher=lambda u: "")
        # Act
        result, _ = toolset.dispatch(
            "get_work_fulltext", {"source_url": "https://doi.org/10.9/nope"}
        )
        # Assert
        self.assertIn("error", result)

    def test_read_budget_is_enforced(self):
        # Arrange: a one-read budget; the second read is refused.
        _, toolset, url = self._toolset_with_work(
            pdf_text_fetcher=lambda u: "text", max_fulltext_fetches=1
        )
        # Act
        first, _ = toolset.dispatch("get_work_fulltext", {"source_url": url})
        second, _ = toolset.dispatch("get_work_fulltext", {"source_url": url})
        # Assert
        self.assertNotIn("error", first)
        self.assertIn("budget", second["error"].lower())
