from unittest.mock import Mock

from django.test import TestCase

from orcid.services import OrcidEmailService


class OrcidEmailServiceTests(TestCase):

    def setUp(self):
        self.mock_client = Mock()
        self.service = OrcidEmailService(client=self.mock_client)

    def test_fetch_returns_verified_edu_emails(self):
        # Arrange
        self.mock_client.get_email_data.return_value = {
            "email": [
                {"email": "user@stanford.edu", "verified": True},
                {"email": "user@gmail.com", "verified": True},
                {"email": "user@mit.edu", "verified": False},
            ]
        }

        # Act
        result = self.service.fetch_verified_edu_emails("0000-0001", "token")

        # Assert
        self.assertEqual(result, ["user@stanford.edu"])

    def test_fetch_returns_empty_when_no_edu_emails(self):
        # Arrange
        self.mock_client.get_email_data.return_value = {
            "email": [{"email": "user@gmail.com", "verified": True}]
        }

        # Act
        result = self.service.fetch_verified_edu_emails("0000-0001", "token")

        # Assert
        self.assertEqual(result, [])

    def test_is_edu_matches_academic_domains(self):
        # Act & Assert
        self.assertTrue(self.service._is_edu("user@stanford.edu"))
        self.assertTrue(self.service._is_edu("prof@cam.ac.uk"))
        self.assertFalse(self.service._is_edu("user@gmail.com"))
