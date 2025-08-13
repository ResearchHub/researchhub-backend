from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from rest_framework import status
from rest_framework.response import Response

from analytics.amplitude import Amplitude, UserActivityTypes, track_event

User = get_user_model()


class AmplitudeTests(TestCase):
    def setUp(self):
        self.amplitude = Amplitude()

    def test_build_user_properties_anonymous_user(self):
        """Test _build_user_properties with an anonymous user."""
        # Arrange
        anonymous_user = AnonymousUser()

        # Act
        user_id, user_properties = self.amplitude._build_user_properties(anonymous_user)

        # Assert
        self.assertEqual(user_id, "")
        self.assertEqual(user_properties["email"], "")
        self.assertEqual(user_properties["first_name"], "Anonymous")
        self.assertEqual(user_properties["last_name"], "Anonymous")
        self.assertEqual(user_properties["reputation"], 0)
        self.assertFalse(user_properties["is_suspended"])
        self.assertFalse(user_properties["probable_spammer"])
        self.assertEqual(user_properties["invited_by_id"], 0)
        self.assertFalse(user_properties["is_hub_editor"])
        self.assertFalse(user_properties["is_verified"])

    def test_build_user_properties_authenticated_user(self):
        """Test _build_user_properties with an authenticated user."""
        # Arrange
        user = User.objects.create(
            first_name="firstName1",
            last_name="lastName1",
            email="email1@researchhub.com",
        )
        user.reputation = 500
        user.is_suspended = False
        user.probable_spammer = False
        user.save()

        # Act
        user_id, user_properties = self.amplitude._build_user_properties(user)

        # Assert
        self.assertEqual(user_id, f"{user.id:0>6}")
        self.assertEqual(user_properties["email"], "email1@researchhub.com")
        self.assertEqual(user_properties["first_name"], "firstName1")
        self.assertEqual(user_properties["last_name"], "lastName1")
        self.assertEqual(user_properties["reputation"], 500)
        self.assertFalse(user_properties["is_suspended"])
        self.assertFalse(user_properties["probable_spammer"])
        self.assertIsNone(user_properties["invited_by_id"])
        self.assertFalse(user_properties["is_hub_editor"])
        self.assertFalse(user_properties["is_verified"])


class TrackEventDecoratorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            first_name="TestUser",
            last_name="TestUser",
            email="test@researchhub.com",
        )

        # Mock view and request objects
        self.mock_view = MagicMock()
        self.mock_view.__class__.__name__ = "PaperViewSet"
        self.mock_view.basename = "paper"
        self.mock_view.action = "upvote"
        self.mock_view.queryset = MagicMock()
        self.mock_view.queryset.model._meta.model_name = "paper"

        self.mock_request = MagicMock()
        self.mock_request.user = self.user
        self.mock_request.path = "/api/papers/"

    @patch("analytics.amplitude.DEVELOPMENT", False)
    @patch("analytics.amplitude.Amplitude.build_hit")
    @patch("analytics.amplitude.track_user_activity")
    def test_track_event_upvote_triggers_user_activity(
        self, mock_track_activity, mock_build_hit
    ):
        """Test that @track_event on upvote method triggers UPVOTE user activity."""
        # Arrange
        mock_response = Response({"id": 123}, status=status.HTTP_200_OK)
        mock_build_hit.return_value = None

        @track_event
        def upvote_method(self, request, *args, **kwargs):
            return mock_response

        # Act
        result = upvote_method(self.mock_view, self.mock_request)

        # Assert
        self.assertEqual(result, mock_response)
        mock_build_hit.assert_called_once()
        mock_track_activity.assert_called_once_with(
            self.user,
            UserActivityTypes.UPVOTE,
            {"content_type": "paper", "object_id": 123},
        )

    @patch("analytics.amplitude.DEVELOPMENT", False)
    @patch("analytics.amplitude.Amplitude.build_hit")
    @patch("analytics.amplitude.track_user_activity")
    def test_track_event_comment_triggers_user_activity(
        self, mock_track_activity, mock_build_hit
    ):
        """Test that @track_event on create_rh_comment method triggers COMMENT user activity."""
        # Arrange
        mock_view = MagicMock()
        mock_view.__class__.__name__ = "RhCommentViewSet"
        mock_view.basename = "rh_comments"
        mock_view.action = "create_rh_comment"

        mock_response = Response(
            {
                "id": 456,
                "comment_type": "GENERAL",
                "thread": 789,
                "is_public": True,
                "is_removed": False,
            },
            status=status.HTTP_200_OK,
        )

        mock_build_hit.return_value = None

        @track_event
        def create_rh_comment_method(self, request, *args, **kwargs):
            return mock_response

        # Act
        result = create_rh_comment_method(mock_view, self.mock_request)

        # Assert
        self.assertEqual(result, mock_response)
        mock_build_hit.assert_called_once()
        mock_track_activity.assert_called_once_with(
            self.user,
            UserActivityTypes.COMMENT,
            {"comment_id": 456, "comment_type": "GENERAL", "thread_id": 789},
        )

    @patch("analytics.amplitude.DEVELOPMENT", False)
    @patch("analytics.amplitude.Amplitude.build_hit")
    @patch("analytics.amplitude.track_user_activity")
    def test_track_event_peer_review_comment_not_tracked(
        self, mock_track_activity, mock_build_hit
    ):
        """Test that peer review comments are not tracked as COMMENT user activity."""
        # Arrange
        mock_view = MagicMock()
        mock_view.__class__.__name__ = "RhCommentViewSet"
        mock_view.basename = "rh_comments"
        mock_view.action = "create_rh_comment"

        mock_response = Response(
            {
                "id": 456,
                "comment_type": "PEER_REVIEW",
                "thread": 789,
                "is_public": True,
                "is_removed": False,
            },
            status=status.HTTP_200_OK,
        )

        mock_build_hit.return_value = None

        @track_event
        def create_rh_comment_method(self, request, *args, **kwargs):
            return mock_response

        # Act
        result = create_rh_comment_method(mock_view, self.mock_request)

        # Assert
        self.assertEqual(result, mock_response)
        mock_build_hit.assert_called_once()
        # Should not call track_user_activity for peer review comments
        mock_track_activity.assert_not_called()

    @patch("analytics.amplitude.DEVELOPMENT", False)
    @patch("analytics.amplitude.Amplitude.build_hit")
    @patch("analytics.amplitude.track_user_activity")
    def test_track_event_review_comment_not_tracked(
        self, mock_track_activity, mock_build_hit
    ):
        """Test that review comments are not tracked as COMMENT user activity."""
        # Arrange
        mock_view = MagicMock()
        mock_view.__class__.__name__ = "RhCommentViewSet"
        mock_view.basename = "rh_comments"
        mock_view.action = "create_rh_comment"

        mock_response = Response(
            {
                "id": 456,
                "comment_type": "REVIEW",
                "thread": 789,
                "is_public": True,
                "is_removed": False,
            },
            status=status.HTTP_200_OK,
        )

        mock_build_hit.return_value = None

        @track_event
        def create_rh_comment_method(self, request, *args, **kwargs):
            return mock_response

        # Act
        result = create_rh_comment_method(mock_view, self.mock_request)

        # Assert
        self.assertEqual(result, mock_response)
        mock_build_hit.assert_called_once()
        # Should not call track_user_activity for review comments
        mock_track_activity.assert_not_called()

    @patch("analytics.amplitude.DEVELOPMENT", False)
    @patch("analytics.amplitude.Amplitude.build_hit")
    @patch("analytics.amplitude.track_user_activity")
    def test_track_event_review_create_triggers_user_activity(
        self, mock_track_activity, mock_build_hit
    ):
        """Test that @track_event on review create method triggers PEER_REVIEW user activity."""
        # Arrange
        mock_view = MagicMock()
        mock_view.__class__.__name__ = "ReviewViewSet"
        mock_view.basename = "review"
        mock_view.action = "create"

        mock_response = Response(
            {
                "id": 101,
                "score": 8.5,
                "content_type": "rhcommentmodel",
                "object_id": 202,
            },
            status=status.HTTP_200_OK,
        )

        mock_build_hit.return_value = None

        @track_event
        def create_review_method(self, request, *args, **kwargs):
            return mock_response

        # Act
        result = create_review_method(mock_view, self.mock_request)

        # Assert
        self.assertEqual(result, mock_response)
        mock_build_hit.assert_called_once()
        mock_track_activity.assert_called_once_with(
            self.user,
            UserActivityTypes.PEER_REVIEW,
            {
                "review_id": 101,
                "score": 8.5,
                "content_type": "rhcommentmodel",
                "object_id": 202,
            },
        )

    @patch("analytics.amplitude.DEVELOPMENT", False)
    @patch("analytics.amplitude.Amplitude.build_hit")
    @patch("analytics.amplitude.track_user_activity")
    def test_track_event_fundraise_contribution_triggers_user_activity(
        self, mock_track_activity, mock_build_hit
    ):
        """Test that @track_event on fundraise contribution method triggers FUND user activity."""
        # Arrange
        mock_view = MagicMock()
        mock_view.__class__.__name__ = "FundraiseViewSet"
        mock_view.basename = "fundraise"
        mock_view.action = "create_contribution"

        mock_response = Response(
            {"id": 303, "amount": "100.00"}, status=status.HTTP_200_OK
        )

        mock_build_hit.return_value = None

        @track_event
        def create_contribution_method(self, request, *args, **kwargs):
            return mock_response

        # Act
        result = create_contribution_method(mock_view, self.mock_request, pk=404)

        # Assert
        self.assertEqual(result, mock_response)
        mock_build_hit.assert_called_once()
        mock_track_activity.assert_called_once_with(
            self.user,
            UserActivityTypes.FUND,
            {
                "purchase_id": 303,
                "amount": "100.00",
                "content_type": "fundraise",
                "object_id": 404,
            },
        )

    @patch("analytics.amplitude.DEVELOPMENT", False)
    @patch("analytics.amplitude.Amplitude.build_hit")
    @patch("analytics.amplitude.track_user_activity")
    def test_track_event_boost_purchase_triggers_user_activity(
        self, mock_track_activity, mock_build_hit
    ):
        """Test that @track_event on boost purchase method triggers TIP user activity."""
        # Arrange
        mock_view = MagicMock()
        mock_view.__class__.__name__ = "PurchaseViewSet"
        mock_view.basename = "purchase"
        mock_view.action = "create"

        mock_response = Response(
            {
                "id": 505,
                "amount": "50.00",
                "purchase_type": "BOOST",
                "content_type": "rhcommentmodel",
                "object_id": 606,
            },
            status=status.HTTP_200_OK,
        )

        mock_build_hit.return_value = None

        @track_event
        def create_purchase_method(self, request, *args, **kwargs):
            return mock_response

        # Act
        result = create_purchase_method(mock_view, self.mock_request)

        # Assert
        self.assertEqual(result, mock_response)
        mock_build_hit.assert_called_once()
        mock_track_activity.assert_called_once_with(
            self.user,
            UserActivityTypes.TIP,
            {
                "purchase_id": 505,
                "amount": "50.00",
                "purchase_type": "BOOST",
                "content_type": "rhcommentmodel",
                "object_id": 606,
            },
        )

    @patch("analytics.amplitude.DEVELOPMENT", False)
    @patch("analytics.amplitude.Amplitude.build_hit")
    @patch("analytics.amplitude.track_user_activity")
    def test_track_event_non_boost_purchase_not_tracked(
        self, mock_track_activity, mock_build_hit
    ):
        """Test that non-boost purchases are not tracked as TIP user activity."""
        # Arrange
        mock_view = MagicMock()
        mock_view.__class__.__name__ = "PurchaseViewSet"
        mock_view.basename = "purchase"
        mock_view.action = "create"

        mock_response = Response(
            {
                "id": 505,
                "amount": "50.00",
                "purchase_type": "DOI",
                "content_type": "paper",
                "object_id": 606,
            },
            status=status.HTTP_200_OK,
        )

        mock_build_hit.return_value = None

        @track_event
        def create_purchase_method(self, request, *args, **kwargs):
            return mock_response

        # Act
        result = create_purchase_method(mock_view, self.mock_request)

        # Assert
        self.assertEqual(result, mock_response)
        mock_build_hit.assert_called_once()
        # Should not call track_user_activity for non-boost purchases
        mock_track_activity.assert_not_called()

    @patch("analytics.amplitude.DEVELOPMENT", False)
    @patch("analytics.amplitude.Amplitude.build_hit")
    @patch("analytics.amplitude.track_user_activity")
    def test_track_event_paper_submission_triggers_user_activity(
        self, mock_track_activity, mock_build_hit
    ):
        """Test that @track_event on paper submission method triggers JOURNAL_SUBMISSION user activity."""
        # Arrange
        mock_view = MagicMock()
        mock_view.__class__.__name__ = "PaperSubmissionViewSet"
        mock_view.basename = "papersubmission"
        mock_view.action = "create"

        mock_response = Response(
            {
                "id": 707,
                "paper_status": "INITIATED",
                "doi": "10.1234/test.123",
                "url": "https://example.com/paper.pdf",
            },
            status=status.HTTP_200_OK,
        )

        mock_build_hit.return_value = None

        @track_event
        def create_submission_method(self, request, *args, **kwargs):
            return mock_response

        # Act
        result = create_submission_method(mock_view, self.mock_request)

        # Assert
        self.assertEqual(result, mock_response)
        mock_build_hit.assert_called_once()
        mock_track_activity.assert_called_once_with(
            self.user,
            UserActivityTypes.JOURNAL_SUBMISSION,
            {
                "submission_id": 707,
                "paper_status": "INITIATED",
                "doi": "10.1234/test.123",
                "url": "https://example.com/paper.pdf",
            },
        )

    @patch("analytics.amplitude.DEVELOPMENT", False)
    @patch("analytics.amplitude.Amplitude.build_hit")
    @patch("analytics.amplitude.track_user_activity")
    def test_track_event_anonymous_user_not_tracked(
        self, mock_track_activity, mock_build_hit
    ):
        """Test that anonymous users don't trigger user activity tracking."""
        # Arrange
        anonymous_request = MagicMock()
        anonymous_request.user = AnonymousUser()

        mock_response = Response({"id": 123}, status=status.HTTP_200_OK)
        mock_build_hit.return_value = None

        @track_event
        def upvote_method(self, request, *args, **kwargs):
            return mock_response

        # Act
        result = upvote_method(self.mock_view, anonymous_request)

        # Assert
        self.assertEqual(result, mock_response)
        mock_build_hit.assert_called_once()
        # Should not call track_user_activity for anonymous users
        mock_track_activity.assert_not_called()

    @patch("analytics.amplitude.DEVELOPMENT", False)
    @patch("analytics.amplitude.track_user_activity")
    def test_track_event_error_response_not_tracked(self, mock_track_activity):
        """Test that error responses don't trigger user activity tracking."""
        # Arrange
        error_response = Response(
            {"error": "Bad request"}, status=status.HTTP_400_BAD_REQUEST
        )

        @track_event
        def upvote_method(self, request, *args, **kwargs):
            return error_response

        # Act
        result = upvote_method(self.mock_view, self.mock_request)

        # Assert
        self.assertEqual(result, error_response)
        # Should not call track_user_activity for error responses
        mock_track_activity.assert_not_called()

    @patch("analytics.amplitude.DEVELOPMENT", True)
    @patch("analytics.amplitude.track_user_activity")
    def test_track_event_development_mode_not_tracked(self, mock_track_activity):
        """Test that DEVELOPMENT mode doesn't trigger tracking."""
        # Arrange
        mock_response = Response({"id": 123}, status=status.HTTP_200_OK)

        @track_event
        def upvote_method(self, request, *args, **kwargs):
            return mock_response

        # Act
        result = upvote_method(self.mock_view, self.mock_request)

        # Assert
        self.assertEqual(result, mock_response)
        # Should not call track_user_activity in development mode
        mock_track_activity.assert_not_called()
