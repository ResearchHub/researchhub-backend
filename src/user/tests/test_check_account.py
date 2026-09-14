from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
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

    def test_unverified_account_is_still_recognized(self):
        # Arrange
        self.email_address.verified = False
        self.email_address.save()

        # Act
        response = self.check_account(self.user.email.lower())

        # Assert
        self.assertEqual(
            response.data,
            {"exists": True, "auth": "email", "is_verified": False},
        )

    def test_google_account_keeps_its_provider(self):
        # Arrange
        SocialAccount.objects.create(user=self.user, provider="google", uid="123")

        # Act
        response = self.check_account(self.user.email.lower())

        # Assert
        self.assertEqual(
            response.data,
            {"exists": True, "auth": "google", "is_verified": True},
        )
