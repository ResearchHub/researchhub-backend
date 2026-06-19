"""Unit tests for research_ai models."""

from django.test import SimpleTestCase

from research_ai.models import Expert


class ExpertSourceIdsTests(SimpleTestCase):
    def test_source_ids_from_sources(self):
        # Arrange
        expert = Expert(
            sources=[
                {"text": "ORCID", "url": "https://orcid.org/0000-0002-1825-0097"},
                {"text": "OpenAlex", "url": "https://openalex.org/A5023888391"},
            ]
        )
        # Act
        orcid, oa_id = expert.source_ids
        # Assert
        self.assertEqual(orcid, "0000-0002-1825-0097")
        self.assertEqual(oa_id, "A5023888391")

    def test_source_ids_handles_plain_string_sources_and_misses(self):
        # Arrange
        expert = Expert(sources=["https://example.edu/jane", "not a url"])
        # Act
        orcid, oa_id = expert.source_ids
        # Assert
        self.assertIsNone(orcid)
        self.assertIsNone(oa_id)
