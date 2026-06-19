"""Unit tests for the OpenAlex tool layer (grounding + dispatch)."""

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from research_ai.services.researcher_profile.openalex_tools import (
    SUBMIT_PROFILE,
    OpenAlexToolset,
)
from utils.openalex import Work
from utils.tests.openalex_helpers import create_oa_author_record, create_oa_work


class ToolSpecTests(SimpleTestCase):
    def test_exposes_openalex_tools_and_submit(self):
        # Arrange / Act
        names = {
            spec["toolSpec"]["name"]
            for spec in OpenAlexToolset(client=MagicMock()).tool_specs
        }
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


class DispatchTests(SimpleTestCase):
    def test_search_authors_returns_compact_candidate_views(self):
        # Arrange
        client = MagicMock()
        client.search_authors_via_name.return_value = {
            "results": [create_oa_author_record()]
        }
        toolset = OpenAlexToolset(client=client)
        # Act
        result, stop = toolset.dispatch("search_authors", {"name": "Jane Doe"})
        # Assert
        self.assertFalse(stop)
        candidate = result["results"][0]
        self.assertEqual(candidate["openalex_author_id"], "https://openalex.org/A123")
        self.assertEqual(candidate["institutions"], ["Stanford University"])
        self.assertIn("Genomics", candidate["top_topics"])

    def test_get_author_works_records_url_provenance(self):
        # Arrange
        client = MagicMock()
        client.get_works_typed.return_value = [
            Work.from_openalex(
                create_oa_work("Lead Paper", 2024, "first"), author_id=None
            )
        ]
        toolset = OpenAlexToolset(client=client)
        # Act
        result, _ = toolset.dispatch(
            "get_author_works", {"openalex_author_id": "https://openalex.org/A123"}
        )
        # Assert: the returned URLs are remembered for later grounding.
        url = result["works"][0]["source_url"]
        self.assertIn(url, toolset.returned_source_urls)
        self.assertIn("https://example.org/lead-paper.pdf", toolset.returned_pdf_urls)

    def test_submit_profile_captures_input_and_stops(self):
        # Arrange
        toolset = OpenAlexToolset(client=MagicMock())
        payload = {"resolution": {"openalex_author_id": "A1", "confidence": 0.9}}
        # Act
        result, stop = toolset.dispatch(SUBMIT_PROFILE, payload)
        # Assert
        self.assertTrue(stop)
        self.assertTrue(result["received"])
        self.assertEqual(toolset.submitted, payload)

    def test_tool_failure_is_returned_not_raised(self):
        # Arrange
        client = MagicMock()
        client.search_authors_via_name.side_effect = RuntimeError("oa down")
        toolset = OpenAlexToolset(client=client)
        # Act
        result, stop = toolset.dispatch("search_authors", {"name": "Jane"})
        # Assert
        self.assertFalse(stop)
        self.assertIn("oa down", result["error"])
