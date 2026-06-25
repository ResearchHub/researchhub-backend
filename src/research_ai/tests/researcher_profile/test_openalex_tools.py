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
