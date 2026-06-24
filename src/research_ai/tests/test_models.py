"""Unit tests for research_ai models."""

from django.test import SimpleTestCase

from research_ai.models import Expert


class ExpertOrcidTests(SimpleTestCase):
    def test_orcid_from_sources(self):
        # Arrange
        expert = Expert(
            sources=[
                {"text": "ORCID", "url": "https://orcid.org/0000-0002-1825-0097"},
            ]
        )
        # Act
        orcid = expert.orcid
        # Assert
        self.assertEqual(orcid, "0000-0002-1825-0097")

    def test_orcid_handles_plain_string_sources_and_misses(self):
        # Arrange
        expert = Expert(sources=["https://example.edu/jane", "not a url"])
        # Act
        orcid = expert.orcid
        # Assert
        self.assertIsNone(orcid)
