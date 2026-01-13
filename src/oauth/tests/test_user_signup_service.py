from unittest.mock import Mock, patch

from django.test import TestCase, override_settings

from oauth.services.user_signup_service import UserSignupService
from user.tests.helpers import create_random_default_user


class AddToMailchimpTests(TestCase):
    def setUp(self):
        self.mock_amplitude_client = Mock()
        self.mock_mailchimp_client = Mock()
        self.service = UserSignupService(
            amplitude_client=self.mock_amplitude_client,
            mailchimp_client=self.mock_mailchimp_client,
        )
        self.user = create_random_default_user("mailchimp_test")

    @override_settings(
        MAILCHIMP_KEY="test-api-key",
        MAILCHIMP_SERVER="us1",
        MAILCHIMP_LIST_ID="list-123",
    )
    def test_add_to_mailchimp_success(self):
        """
        Test successful addition of user to Mailchimp.
        """
        # Act
        self.service.add_to_mailchimp(self.user)

        # Assert
        self.mock_mailchimp_client.set_config.assert_called_once_with(
            {
                "api_key": "test-api-key",
                "server": "us1",
            }
        )
        self.mock_mailchimp_client.lists.add_list_member.assert_called_once_with(
            "list-123",
            {"email_address": self.user.email, "status": "subscribed"},
        )

    @override_settings(
        MAILCHIMP_KEY="test-api-key",
        MAILCHIMP_SERVER="us1",
        MAILCHIMP_LIST_ID="list-123",
    )
    def test_add_to_mailchimp_handles_exception(self):
        """
        Test that Mailchimp errors are logged but don't raise.
        """
        # Arrange
        self.mock_mailchimp_client.lists.add_list_member.side_effect = Exception(
            "API Error"
        )

        with patch("oauth.services.user_signup_service.logger") as mock_logger:
            # Act
            self.service.add_to_mailchimp(self.user)

            # Assert
            mock_logger.error.assert_called_once()
            call_args = mock_logger.error.call_args[0][0]
            self.assertIn(str(self.user.id), call_args)
            self.assertIn("API Error", call_args)


class TrackSignupTests(TestCase):
    def setUp(self):
        self.mock_amplitude_client = Mock()
        self.mock_mailchimp_client = Mock()
        self.service = UserSignupService(
            amplitude_client=self.mock_amplitude_client,
            mailchimp_client=self.mock_mailchimp_client,
        )
        self.user = create_random_default_user("amplitude_test")
        self.mock_request = Mock()

    def test_track_signup_success(self):
        """
        Test successful tracking of signup in Amplitude.
        """
        # Act
        self.service.track_signup(self.mock_request, self.user)

        # Assert
        self.assertEqual(self.mock_request.user, self.user)
        self.mock_amplitude_client.build_hit.assert_called_once()

        call_args = self.mock_amplitude_client.build_hit.call_args
        res, view, request = call_args[0]

        self.assertEqual(res.data["id"], self.user.id)
        self.assertEqual(view.basename, "user")
        self.assertEqual(view.action, "signup")
        self.assertEqual(request, self.mock_request)

    def test_track_signup_passes_kwargs(self):
        """
        Test that kwargs are passed to Amplitude build_hit.
        """
        # Arrange
        extra_data = {"source": "google", "campaign": "campaign1"}

        # Act
        self.service.track_signup(self.mock_request, self.user, **extra_data)

        # Assert
        call_kwargs = self.mock_amplitude_client.build_hit.call_args[1]
        self.assertEqual(call_kwargs["source"], "google")
        self.assertEqual(call_kwargs["campaign"], "campaign1")

    def test_track_signup_handles_exception(self):
        """
        Test that Amplitude errors are logged but don't raise.
        """
        # Arrange
        self.mock_amplitude_client.build_hit.side_effect = Exception("Amplitude Error")

        with patch("oauth.services.user_signup_service.logger") as mock_logger:
            # Act
            self.service.track_signup(self.mock_request, self.user)

            # Assert
            mock_logger.error.assert_called_once()
            call_args = mock_logger.error.call_args[0][0]
            self.assertIn(str(self.user.id), call_args)
            self.assertIn("Amplitude Error", call_args)
