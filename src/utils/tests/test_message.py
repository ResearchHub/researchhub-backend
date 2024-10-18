from django.test import TestCase, override_settings

from utils.message import is_valid_email


class MessageUtilsTests(TestCase):

    def test_is_valid_email(self):
        # Arrange
        email = "name1@researchhub.com"

        # Act
        result = is_valid_email(email)

        # Assert
        self.assertTrue(result)

    @override_settings(TESTING=False, EMAIL_WHITELIST=["name1@researchhub.com"])
    def test_is_valid_email_if_in_whitelist(self):
        # Arrange
        email = "name1@researchhub.com"

        # Act
        result = is_valid_email(email)

        # Assert
        self.assertTrue(result)

    @override_settings(TESTING=False, EMAIL_WHITELIST=["other@researchhub.com"])
    def test_is_valid_email_fails_if_not_in_whitelist(self):
        # Arrange
        email = "name1@researchhub.com"

        # Act
        result = is_valid_email(email)

        # Assert
        self.assertFalse(result)
