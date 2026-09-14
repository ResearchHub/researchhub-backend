from allauth.account.models import EmailAddress
from rest_framework.test import APIClient

from user.models import User
from utils.test_helpers import AWSMockTestCase


class CheckAccountTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create(email="Existing.User@example.com")
        self.email_address = EmailAddress.objects.create(
            user=self.user, email=self.user.email, verified=True, primary=True
        )

    def check_account(self, email):
        return APIClient().post(
            "/api/user/check_account/", {"email": email}, format="json"
        )

    def test_recognizes_existing_email_regardless_of_case_or_whitespace(self):
        # Arrange
        emails = [
            self.user.email,
            self.user.email.lower(),
            self.user.email.upper(),
            f"  {self.user.email.lower()}  ",
        ]
        for email in emails:
            with self.subTest(email=email):
                # Act
                response = self.check_account(email)

                # Assert
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.data,
                    {"exists": True, "auth": "email", "is_verified": True},
                )

    def test_unknown_email_does_not_exist(self):
        # Arrange
        email = "unknown@example.com"

        # Act
        response = self.check_account(email)

        # Assert
        self.assertEqual(response.data, {"exists": False})

    def test_invalid_email_returns_validation_error(self):
        # Arrange
        payloads = [
            {},
            {"email": None},
            {"email": ""},
            {"email": "   "},
            {"email": "not-an-email"},
            {"email": 123},
            {"email": True},
            {"email": []},
            {"email": {}},
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                # Act
                response = APIClient().post(
                    "/api/user/check_account/", payload, format="json"
                )

                # Assert
                self.assertEqual(response.status_code, 400)
                self.assertIn("email", response.data)
