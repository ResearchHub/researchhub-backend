from unittest.mock import Mock, patch

from allauth.account.signals import user_signed_up
from django.test import TestCase

import oauth.signals  # noqa: F401 - register signals
from user.tests.helpers import create_random_default_user


class UserSignupSignalTests(TestCase):
    """
    Tests the signals for user signup handling.
    """

    def setUp(self):
        self.user = create_random_default_user("signal_test")
        self.mock_request = Mock()

    @patch("oauth.signals.UserSignupService")
    def test_handle_user_signup_adds_to_mailchimp(self, mock_service_class):
        """
        Tests that the user is added to Mailchimp on signup.
        """
        # Arrange
        mock_service = Mock()
        mock_service_class.return_value = mock_service

        # Act
        user_signed_up.send(
            sender=self.__class__, request=self.mock_request, user=self.user
        )

        # Assert
        mock_service.add_to_mailchimp.assert_called_once_with(self.user)

    @patch("oauth.signals.UserSignupService")
    def test_handle_user_signup_tracks_signup(self, mock_service_class):
        """
        Tests that the signup is tracked in Amplitude on user signup.
        """
        # Arrange
        mock_service = Mock()
        mock_service_class.return_value = mock_service

        # Act
        user_signed_up.send(
            sender=self.__class__, request=self.mock_request, user=self.user
        )

        # Assert
        mock_service.track_signup.assert_called_once()
        call_args = mock_service.track_signup.call_args
        self.assertEqual(call_args[0][0], self.mock_request)
        self.assertEqual(call_args[0][1], self.user)
