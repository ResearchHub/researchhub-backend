"""
Tests for MedRxiv mapper.
"""

from unittest.mock import PropertyMock, patch

from django.test import TestCase

from hub.models import Hub
from paper.ingestion.mappers import MedRxivMapper


class TestMedRxivMapper(TestCase):
    """Test cases for MedRxiv mapper using Django TestCase."""

    def setUp(self):
        """Set up test fixtures."""
        # Sample MedRxiv record
        self.sample_record = {
            "title": "COVID-19 vaccine effectiveness in healthcare workers",
            "authors": "Smith, J. A.; Johnson, B. C.; Williams, D. E.",
            "author_corresponding": "Jane A. Smith",
            "author_corresponding_institution": "University Medical Center",
            "doi": "10.1101/2024.12.31.24319876",
            "date": "2025-01-01",
            "version": "2",
            "type": "new results",
            "license": "cc_by",
            "category": "epidemiology",
            "jatsxml": (
                "https://www.medrxiv.org/content/early/2025/01/01/"
                "2024.12.31.24319876.source.xml"
            ),
            "abstract": (
                "This study evaluates the effectiveness of COVID-19 vaccines "
                "in healthcare workers during the omicron variant surge."
            ),
            "funder": "NIH",
            "published": "NA",
            "server": "medRxiv",
        }

    def test_map_to_hubs(self):
        """
        Test map_to_hubs returns the MedRxiv hub.
        """
        # Arrange
        hub, _ = Hub.objects.get_or_create(
            slug="medrxiv",
            defaults={
                "name": "MedRxiv",
                "namespace": Hub.Namespace.JOURNAL,
            },
        )
        mapper = MedRxivMapper(None)

        # Act
        hubs = mapper.map_to_hubs(self.sample_record)

        # Assert
        self.assertEqual(len(hubs), 1)
        self.assertEqual(hubs[0], hub)
        self.assertEqual(hubs[0].slug, "medrxiv")
        self.assertEqual(hubs[0].namespace, Hub.Namespace.JOURNAL)

    @patch.object(MedRxivMapper, "preprint_hub", new_callable=PropertyMock)
    def test_map_to_hubs_without_existing_hub(self, mock_preprint_hub):
        """
        Test map_to_hubs returns empty list when MedRxiv hub doesn't exist.
        """
        # Arrange
        mock_preprint_hub.return_value = None
        mapper = MedRxivMapper(None)

        # Act
        hubs = mapper.map_to_hubs(self.sample_record)

        # Assert
        self.assertEqual(len(hubs), 0)
        self.assertEqual(hubs, [])
