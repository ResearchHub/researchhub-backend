from unittest.mock import Mock

from allauth.socialaccount.models import SocialAccount, SocialToken
from django.test import TestCase

from orcid.services import OrcidFetchService
from orcid.tests.helpers import OrcidTestHelper
from user.related_models.author_model import Author
from user.tests.helpers import create_random_default_user


class OrcidFetchServiceTests(TestCase):
    def setUp(self) -> None:
        """Set up the service with a mocked email dependency."""
        self.mock_email_service = Mock()
        self.service = OrcidFetchService(email_service=self.mock_email_service)

    def test_sync_raises_for_invalid_author(self) -> None:
        """Sync raises when the author does not exist or has no ORCID ID."""
        # Arrange
        user = create_random_default_user("no_orcid")

        # Act & Assert
        with self.assertRaises(ValueError):
            self.service.sync_orcid(999999)
        with self.assertRaises(ValueError):
            self.service.sync_orcid(user.author_profile.id)

    def test_sync_edu_emails_skips_when_no_user(self) -> None:
        """Email synchronization skips authors without a user."""
        # Act
        self.service._sync_edu_emails(None, "0000-0001")

        # Assert
        self.mock_email_service.fetch_verified_edu_emails.assert_not_called()

    def test_sync_updates_social_account_edu_emails(self) -> None:
        """Sync stores verified education emails on the ORCID social account."""
        # Arrange
        user = OrcidTestHelper.create_connected_user()
        app = OrcidTestHelper.create_app()
        account = SocialAccount.objects.get(user=user)
        SocialToken.objects.create(account=account, token="access_token", app=app)
        self.mock_email_service.fetch_verified_edu_emails.return_value = [
            "user@stanford.edu"
        ]

        # Act
        self.service.sync_orcid(user.author_profile.id)

        # Assert
        account.refresh_from_db()
        self.assertEqual(
            account.extra_data["verified_edu_emails"], ["user@stanford.edu"]
        )

    def test_sync_updates_author_h_index_from_merged_author(self) -> None:
        """Sync copies author stats from the best merged paper author."""
        # Arrange
        user = OrcidTestHelper.create_connected_user()
        Author.objects.create(
            first_name="Paper",
            last_name="Author",
            h_index=15,
            i10_index=8,
            two_year_mean_citedness=3.5,
            merged_with_author=user.author_profile,
            created_source=Author.SOURCE_OPENALEX,
        )

        # Act
        self.service.sync_orcid(user.author_profile.id)

        # Assert
        user.author_profile.refresh_from_db()
        self.assertEqual(user.author_profile.h_index, 15)
        self.assertEqual(user.author_profile.i10_index, 8)
        self.assertEqual(user.author_profile.two_year_mean_citedness, 3.5)
