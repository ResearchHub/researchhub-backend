from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from paper.models import Paper

FETCH_REGISTRATION = (
    "paper.ingestion.clients.registrations.osf.OSFRegistrationClient.fetch_registration"
)


class ImportOSFRegistrationCommandTests(TestCase):
    @patch(FETCH_REGISTRATION)
    def test_imports_registration(self, mock_fetch):
        # Arrange
        mock_fetch.return_value = {
            "id": "wzubg",
            "attributes": {
                "title": "Research plan title",
                "date_registered": "2026-08-31T21:21:16.905334",
                "withdrawn": False,
                "registration_responses": {"340-18": "Outcomes report title"},
            },
            "provider": "Lifecycle Journal",
            "url": "https://osf.io/wzubg/",
            "contributors": [],
            "response_labels": {"340-18": "Short Title:"},
        }
        out = StringIO()

        # Act
        call_command(
            "import_osf_registration",
            "https://doi.org/10.17605/OSF.IO/WZUBG",
            stdout=out,
        )

        # Assert
        paper = Paper.objects.get(doi="10.17605/osf.io/wzubg")
        self.assertEqual(paper.title, "Outcomes report title")
        mock_fetch.assert_called_once_with("wzubg")
        self.assertIn(f"as paper {paper.id}", out.getvalue())

    @patch(FETCH_REGISTRATION)
    def test_reports_missing_registration(self, mock_fetch):
        # Arrange
        mock_fetch.return_value = None
        err = StringIO()

        # Act
        call_command("import_osf_registration", "10.17605/OSF.IO/ABCDE", stderr=err)

        # Assert
        self.assertIn("No public OSF registration imported", err.getvalue())
        self.assertFalse(Paper.objects.exists())

    @patch(FETCH_REGISTRATION)
    def test_rejects_non_osf_dois(self, mock_fetch):
        # Act & Assert
        with self.assertRaises(CommandError):
            call_command("import_osf_registration", "10.1234/test.123")
        mock_fetch.assert_not_called()
