"""
Tests for OSF registration import service.
"""

from unittest.mock import Mock

from django.test import TestCase

from paper.ingestion.services.osf_registration_service import OSFRegistrationService
from paper.models import Paper


class TestOSFRegistrationService(TestCase):
    def setUp(self):
        self.client = Mock()
        self.service = OSFRegistrationService(client=self.client)
        self.record = {
            "id": "wzubg",
            "attributes": {
                "title": "Outcomes report",
                "date_registered": "2026-08-31T21:21:16.905334",
                "withdrawn": False,
            },
            "provider": "Lifecycle Journal",
            "url": "https://osf.io/wzubg/",
            "contributors": [],
            "response_labels": {},
        }

    def test_get_guid(self):
        # Act & Assert
        self.assertEqual(
            OSFRegistrationService.get_guid("10.17605/OSF.IO/WZUBG"), "wzubg"
        )
        self.assertEqual(
            OSFRegistrationService.get_guid("10.17605/osf.io/wzubg"), "wzubg"
        )
        self.assertIsNone(OSFRegistrationService.get_guid("10.31234/osf.io/sd2hq_v1"))
        self.assertIsNone(OSFRegistrationService.get_guid("10.1234/test.123"))

    def test_import_by_doi(self):
        # Arrange
        self.client.fetch_registration.return_value = self.record

        # Act
        first = self.service.import_by_doi("10.17605/osf.io/wzubg")
        second = self.service.import_by_doi("10.17605/osf.io/wzubg")

        # Assert
        self.client.fetch_registration.assert_called_with("wzubg")
        self.assertEqual(first.doi, "10.17605/osf.io/wzubg")
        self.assertEqual(first.title, "Outcomes report")
        self.assertIsNotNone(first.unified_document)
        self.assertEqual(second.id, first.id)
        self.assertEqual(Paper.objects.filter(doi="10.17605/osf.io/wzubg").count(), 1)

    def test_import_by_doi_not_public(self):
        # Arrange
        self.client.fetch_registration.return_value = None

        # Act
        paper = self.service.import_by_doi("10.17605/osf.io/abcde")

        # Assert
        self.assertIsNone(paper)
        self.assertFalse(Paper.objects.filter(doi="10.17605/osf.io/abcde").exists())

    def test_import_by_doi_non_osf_doi(self):
        # Act
        paper = self.service.import_by_doi("10.1234/test.123")

        # Assert
        self.assertIsNone(paper)
        self.client.fetch_registration.assert_not_called()
