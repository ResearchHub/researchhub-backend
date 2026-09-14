"""Unit tests for the OpenAlex tool layer (core Tools, grounding, dispatch)."""

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from research_ai.services.researcher_profile.openalex_tools import (
    SUBMIT_PROFILE,
    OpenAlexToolset,
)
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
                "get_work_abstract",
                "search_work_fulltext",
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
        client.get_works.return_value = (
            [create_oa_work("Lead Paper", 2024, "first")],
            "next-page",
        )
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
        self.assertNotIn("abstract", result["works"][0])
        self.assertNotIn("pdf_url", result["works"][0])
        self.assertTrue(result["works"][0]["has_abstract"])
        self.assertEqual(result["next_cursor"], "next-page")
        self.assertTrue(result["has_more"])

    def test_get_author_works_passes_cursor_and_keeps_broad_page_size(self):
        # Arrange
        client = MagicMock()
        client.get_works.return_value = ([], "later")
        toolset = OpenAlexToolset(client=client).as_toolset()

        # Act
        result, _ = toolset.dispatch(
            "get_author_works",
            {
                "openalex_author_id": "https://openalex.org/A123",
                "cursor": "prior-cursor",
                "max_results": 40,
            },
        )

        # Assert
        client.get_works.assert_called_once_with(
            openalex_author_id="https://openalex.org/A123",
            next_cursor="prior-cursor",
            batch_size=40,
            sort="publication_date:desc",
            open_access_only=True,
        )
        self.assertEqual(result["next_cursor"], "later")

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


class WorkDetailTests(SimpleTestCase):
    def _toolset_with_work(self, **kwargs):
        """A toolset that has already returned one work (so it can be read)."""
        client = MagicMock()
        client.get_works.return_value = (
            [create_oa_work("Lead Paper", 2024, "first")],
            None,
        )
        provider = OpenAlexToolset(client=client, **kwargs)
        toolset = provider.as_toolset()
        result, _ = toolset.dispatch(
            "get_author_works", {"openalex_author_id": "https://openalex.org/A123"}
        )
        return provider, toolset, result["works"][0]["source_url"]

    def test_fetches_abstract_separately_from_work_listing(self):
        # Arrange
        _, toolset, url = self._toolset_with_work(pdf_text_fetcher=lambda _url: "")

        # Act
        result, stop = toolset.dispatch("get_work_abstract", {"source_url": url})

        # Assert
        self.assertFalse(stop)
        self.assertEqual(result["abstract"], "Abstract text")

    def test_fulltext_search_returns_relevant_passages_not_the_paper(self):
        # Arrange: a stub fetcher stands in for the PDF download/extract.
        text = (
            "Background material about unrelated observations. " * 40
            + "METHODS: single-cell RNA-seq was performed on tumor samples. "
            + "Additional unrelated discussion. " * 80
        )
        _, toolset, url = self._toolset_with_work(
            pdf_text_fetcher=lambda _pdf_url: text
        )
        # Act
        result, stop = toolset.dispatch(
            "search_work_fulltext",
            {"source_url": url, "query": "single-cell RNA-seq tumor samples"},
        )
        # Assert
        self.assertFalse(stop)
        self.assertNotIn("text", result)
        self.assertGreater(result["match_count"], 0)
        self.assertIn("single-cell", result["passages"][0]["text"])
        self.assertLess(len(result["passages"][0]["text"]), len(text))

    def test_fulltext_search_downweights_terms_common_across_the_document(self):
        # Arrange: "using" appears throughout the paper, while the substantive
        # query term identifies one passage.
        text = (
            "Background using standard controls and routine analysis. " * 100
            + "METHODS: using CRISPR screens to identify resistance genes. "
            + "Discussion using standard controls and routine analysis. " * 100
        )
        _, toolset, url = self._toolset_with_work(
            pdf_text_fetcher=lambda _pdf_url: text
        )

        # Act
        result, _ = toolset.dispatch(
            "search_work_fulltext",
            {"source_url": url, "query": "using CRISPR"},
        )

        # Assert
        self.assertIn("CRISPR", result["passages"][0]["text"])

    def test_fulltext_search_retains_common_research_query_terms(self):
        # Arrange: these terms were previously handled by a manual stop list.
        text = (
            "Unrelated introduction and background. " * 60
            + "This paper reports what happened after using the intervention. "
            + "Unrelated conclusions and references. " * 60
        )
        _, toolset, url = self._toolset_with_work(
            pdf_text_fetcher=lambda _pdf_url: text
        )

        # Act
        result, _ = toolset.dispatch(
            "search_work_fulltext",
            {"source_url": url, "query": "paper what after using"},
        )

        # Assert
        self.assertIn("paper reports", result["passages"][0]["text"])

    def test_fulltext_search_does_not_fall_back_to_abstract(self):
        # Arrange
        _, toolset, url = self._toolset_with_work(pdf_text_fetcher=lambda pdf_url: "")
        # Act
        result, _ = toolset.dispatch(
            "search_work_fulltext", {"source_url": url, "query": "methods"}
        )
        # Assert
        self.assertIn("No readable full text", result["error"])
        self.assertNotIn("Abstract text", str(result))

    def test_fulltext_search_reports_when_source_text_was_truncated(self):
        # Arrange: the only query match falls beyond the bounded search prefix.
        text = "background " * 12000 + "unique-tail-evidence"
        _, toolset, url = self._toolset_with_work(
            pdf_text_fetcher=lambda _pdf_url: text
        )

        # Act
        result, _ = toolset.dispatch(
            "search_work_fulltext",
            {"source_url": url, "query": "unique-tail-evidence"},
        )

        # Assert
        self.assertTrue(result["source_truncated"])
        self.assertEqual(result["searched_characters"], 120000)
        self.assertEqual(result["match_count"], 0)
        self.assertIn("first 120000 characters", result["warning"])

    def test_unknown_source_url_errors(self):
        # Arrange
        _, toolset, _ = self._toolset_with_work(pdf_text_fetcher=lambda u: "")
        # Act
        result, _ = toolset.dispatch(
            "search_work_fulltext",
            {"source_url": "https://doi.org/10.9/nope", "query": "methods"},
        )
        # Assert
        self.assertIn("error", result)

    def test_read_budget_is_enforced(self):
        # Arrange: a one-document budget with two returned works.
        client = MagicMock()
        client.get_works.return_value = (
            [
                create_oa_work("Paper One", 2024, "first"),
                create_oa_work("Paper Two", 2023, "last"),
            ],
            None,
        )
        provider = OpenAlexToolset(
            client=client,
            pdf_text_fetcher=lambda _url: "Methods include microscopy.",
            max_fulltext_fetches=1,
        )
        toolset = provider.as_toolset()
        listed, _ = toolset.dispatch("get_author_works", {"openalex_author_id": "A123"})
        first_url, second_url = [work["source_url"] for work in listed["works"]]
        # Act
        first, _ = toolset.dispatch(
            "search_work_fulltext", {"source_url": first_url, "query": "microscopy"}
        )
        second, _ = toolset.dispatch(
            "search_work_fulltext", {"source_url": second_url, "query": "microscopy"}
        )
        # Assert
        self.assertNotIn("error", first)
        self.assertIn("budget", second["error"].lower())

    def test_repeated_queries_reuse_one_document_fetch(self):
        # Arrange
        calls = []

        def fetch(url):
            calls.append(url)
            return "Methods used microscopy. Results reported biomarkers."

        _, toolset, url = self._toolset_with_work(
            pdf_text_fetcher=fetch, max_fulltext_fetches=1
        )

        # Act
        first, _ = toolset.dispatch(
            "search_work_fulltext", {"source_url": url, "query": "microscopy"}
        )
        second, _ = toolset.dispatch(
            "search_work_fulltext", {"source_url": url, "query": "biomarkers"}
        )

        # Assert
        self.assertNotIn("error", first)
        self.assertNotIn("error", second)
        self.assertEqual(len(calls), 1)
