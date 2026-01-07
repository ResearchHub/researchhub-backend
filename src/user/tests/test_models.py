from decimal import Decimal

from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.test import TestCase

from paper.related_models.authorship_model import Authorship
from paper.related_models.paper_model import Paper
from purchase.related_models.balance_model import Balance
from user.related_models.follow_model import Follow
from user.related_models.user_model import User
from user.tests.helpers import create_user


class AuthorModelsTests(TestCase):
    def setUp(self):
        self.user = create_user(
            email="random@researchhub.com",
            first_name="random",
            last_name="user",
        )

        paper1 = Paper.objects.create(
            title="title1",
            citations=10,
            is_open_access=True,
        )

        paper2 = Paper.objects.create(
            title="title2",
            citations=20,
            is_open_access=False,
        )

        Authorship.objects.create(author=self.user.author_profile, paper=paper1)
        Authorship.objects.create(author=self.user.author_profile, paper=paper2)

    def test_citation_count_property(self):
        self.assertEqual(self.user.author_profile.citation_count, 30)

    def test_paper_count_property(self):
        self.assertEqual(self.user.author_profile.paper_count, 2)

    def test_open_access_pct_property(self):
        self.assertEqual(self.user.author_profile.open_access_pct, 0.5)

    def test_achievements(self):
        self.assertIn("CITED_AUTHOR", self.user.author_profile.achievements)

    def test_is_orcid_connected_false_when_no_account(self):
        # Act
        result = self.user.author_profile.is_orcid_connected

        # Assert
        self.assertFalse(result)

    def test_is_orcid_connected_true_when_account_exists(self):
        # Arrange
        SocialAccount.objects.create(
            user=self.user, provider=OrcidProvider.id, uid="0000-0001-2345-6789"
        )

        # Act
        result = self.user.author_profile.is_orcid_connected

        # Assert
        self.assertTrue(result)

    def test_orcid_verified_edu_email_none_when_no_account(self):
        # Act
        result = self.user.author_profile.orcid_verified_edu_email

        # Assert
        self.assertIsNone(result)

    def test_orcid_verified_edu_email_none_when_no_emails(self):
        # Arrange
        SocialAccount.objects.create(
            user=self.user,
            provider=OrcidProvider.id,
            uid="0000-0001-2345-6789",
            extra_data={"verified_edu_emails": []},
        )

        # Act
        result = self.user.author_profile.orcid_verified_edu_email

        # Assert
        self.assertIsNone(result)

    def test_orcid_verified_edu_email_returns_first_email(self):
        # Arrange
        SocialAccount.objects.create(
            user=self.user,
            provider=OrcidProvider.id,
            uid="0000-0001-2345-6789",
            extra_data={"verified_edu_emails": ["user@stanford.edu", "user@mit.edu"]},
        )

        # Act
        result = self.user.author_profile.orcid_verified_edu_email

        # Assert
        self.assertEqual(result, "user@stanford.edu")
class FollowModelTests(TestCase):
    def setUp(self):
        self.user = create_user(
            email="random@researchhub.com",
            first_name="random",
            last_name="user",
        )

    def test_follow_user(self):
        # Arrange & Act
        follow = Follow.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(User),
            object_id=self.user.id,
        )

        # Assert
        self.assertEqual(follow.user, self.user)
        self.assertEqual(follow.content_type, ContentType.objects.get_for_model(User))
        self.assertEqual(follow.object_id, self.user.id)

    def test_follow_paper(self):
        # Arrange
        paper = Paper.objects.create(title="title1", citations=10, is_open_access=True)

        # Act
        follow = Follow.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=paper.id,
        )

        # Assert
        self.assertEqual(follow.user, self.user)
        self.assertEqual(follow.content_type, ContentType.objects.get_for_model(Paper))
        self.assertEqual(follow.object_id, paper.id)

    def test_follow_unsupported_model(self):
        # Arrange
        with self.assertRaises(ValidationError):
            Follow.objects.create(
                user=self.user,
                content_type=ContentType.objects.get_for_model(Authorship),
                object_id=1,
            )


class UserBalanceTests(TestCase):
    def setUp(self):
        self.user = create_user(
            email="balance@test.com",
            first_name="Balance",
            last_name="Test",
        )
        self.content_type = ContentType.objects.get_for_model(Paper)

    def test_get_balance_excludes_locked_by_default(self):
        # Create regular balance
        Balance.objects.create(
            user=self.user,
            amount="100",
            content_type=self.content_type,
            is_locked=False,
        )

        # Create locked balance
        Balance.objects.create(
            user=self.user,
            amount="50",
            content_type=self.content_type,
            is_locked=True,
            lock_type="FUNDRAISE_CONTRIBUTION",
        )

        # Default behavior should exclude locked funds
        balance = self.user.get_balance()
        self.assertEqual(balance, Decimal("100"))

    def test_get_balance_includes_locked_when_requested(self):
        # Create regular balance
        Balance.objects.create(
            user=self.user,
            amount="100",
            content_type=self.content_type,
            is_locked=False,
        )

        # Create locked balance
        Balance.objects.create(
            user=self.user,
            amount="50",
            content_type=self.content_type,
            is_locked=True,
            lock_type="FUNDRAISE_CONTRIBUTION",
        )

        # When include_locked=True, should include all funds
        balance = self.user.get_balance(include_locked=True)
        self.assertEqual(balance, Decimal("150"))

    def test_get_available_balance(self):
        # Create regular balance
        Balance.objects.create(
            user=self.user,
            amount="200",
            content_type=self.content_type,
            is_locked=False,
        )

        # Create locked balance
        Balance.objects.create(
            user=self.user,
            amount="75",
            content_type=self.content_type,
            is_locked=True,
            lock_type="FUNDRAISE_CONTRIBUTION",
        )

        # Should only return unlocked funds
        available = self.user.get_available_balance()
        self.assertEqual(available, Decimal("200"))

    def test_get_locked_balance_all(self):
        # Create regular balance
        Balance.objects.create(
            user=self.user,
            amount="300",
            content_type=self.content_type,
            is_locked=False,
        )

        # Create locked balances
        Balance.objects.create(
            user=self.user,
            amount="100",
            content_type=self.content_type,
            is_locked=True,
            lock_type="FUNDRAISE_CONTRIBUTION",
        )

        Balance.objects.create(
            user=self.user,
            amount="25",
            content_type=self.content_type,
            is_locked=True,
            lock_type="FUNDRAISE_CONTRIBUTION",
        )

        # Should return total locked funds
        locked = self.user.get_locked_balance()
        self.assertEqual(locked, Decimal("125"))

    def test_get_locked_balance_by_type(self):
        # Create locked balances of different types
        Balance.objects.create(
            user=self.user,
            amount="60",
            content_type=self.content_type,
            is_locked=True,
            lock_type="FUNDRAISE_CONTRIBUTION",
        )

        # Should return only the specified lock type
        fundraise_locked = self.user.get_locked_balance("FUNDRAISE_CONTRIBUTION")
        self.assertEqual(fundraise_locked, Decimal("60"))

    def test_balance_calculations_with_mixed_balances(self):
        # Create mix of locked and unlocked balances
        Balance.objects.create(
            user=self.user,
            amount="500",
            content_type=self.content_type,
            is_locked=False,
        )

        Balance.objects.create(
            user=self.user,
            amount="200",
            content_type=self.content_type,
            is_locked=True,
            lock_type="FUNDRAISE_CONTRIBUTION",
        )

        Balance.objects.create(
            user=self.user,
            amount="100",
            content_type=self.content_type,
            is_locked=False,
        )

        # Test all balance methods
        total_with_locked = self.user.get_balance(include_locked=True)
        available = self.user.get_available_balance()
        locked = self.user.get_locked_balance()
        default_balance = self.user.get_balance()  # Should exclude locked

        self.assertEqual(total_with_locked, Decimal("800"))
        self.assertEqual(available, Decimal("600"))
        self.assertEqual(locked, Decimal("200"))
        self.assertEqual(default_balance, Decimal("600"))  # Same as available

        # Verify math: available + locked = total
        self.assertEqual(available + locked, total_with_locked)
