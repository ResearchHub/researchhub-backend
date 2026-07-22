from decimal import Decimal

from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from paper.related_models.authorship_model import Authorship
from paper.related_models.paper_model import Paper
from purchase.related_models.balance_model import Balance
from reputation.related_models.distribution import Distribution
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from review.models import Review
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

    def test_peer_review_count_only_includes_assessed_reviews(self):
        paper = Paper.objects.create(title="review paper")
        thread = RhCommentThreadModel.objects.create(
            object_id=paper.id,
            content_type=ContentType.objects.get_for_model(Paper),
            created_by=self.user,
        )
        comment_content_type = ContentType.objects.get_for_model(RhCommentModel)

        assessed_comment = RhCommentModel.objects.create(
            created_by=self.user,
            comment_type="REVIEW",
            is_removed=False,
            thread=thread,
        )
        Review.objects.create(
            created_by=self.user,
            content_type=comment_content_type,
            object_id=assessed_comment.id,
            is_assessed=True,
        )

        unassessed_comment = RhCommentModel.objects.create(
            created_by=self.user,
            comment_type="REVIEW",
            is_removed=False,
            thread=thread,
        )
        Review.objects.create(
            created_by=self.user,
            content_type=comment_content_type,
            object_id=unassessed_comment.id,
            is_assessed=False,
        )

        RhCommentModel.objects.create(
            created_by=self.user,
            comment_type="REVIEW",
            is_removed=False,
            thread=thread,
        )

        self.assertEqual(self.user.peer_review_count, 1)

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
        )

        # Default behavior should exclude locked funds
        balance = self.user.get_balance()
        self.assertEqual(balance, Decimal(100))

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
        )

        # When include_locked=True, should include all funds
        balance = self.user.get_balance(include_locked=True)
        self.assertEqual(balance, Decimal(150))

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
        )

        # Should only return unlocked funds
        available = self.user.get_available_balance()
        self.assertEqual(available, Decimal(200))

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
        )

        Balance.objects.create(
            user=self.user,
            amount="25",
            content_type=self.content_type,
            is_locked=True,
        )

        # Should return total locked funds
        locked = self.user.get_locked_balance()
        self.assertEqual(locked, Decimal(125))

    def test_get_locked_balance_returns_all_locked(self):
        # Create locked balance
        Balance.objects.create(
            user=self.user,
            amount="60",
            content_type=self.content_type,
            is_locked=True,
        )

        locked = self.user.get_locked_balance()
        self.assertEqual(locked, Decimal(60))

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

        self.assertEqual(total_with_locked, Decimal(800))
        self.assertEqual(available, Decimal(600))
        self.assertEqual(locked, Decimal(200))
        self.assertEqual(default_balance, Decimal(600))  # Same as available

        # Verify math: available + locked = total
        self.assertEqual(available + locked, total_with_locked)

    def test_allocate_spend_unlocked_only(self):
        Balance.objects.create(
            user=self.user,
            amount="200",
            content_type=self.content_type,
            is_locked=False,
        )
        Balance.objects.create(
            user=self.user,
            amount="100",
            content_type=self.content_type,
            is_locked=True,
        )

        allocations = self.user.allocate_spend(Decimal(150))
        self.assertEqual(len(allocations), 1)
        self.assertFalse(allocations[0]["is_locked"])
        self.assertEqual(allocations[0]["amount"], Decimal(150))

    def test_allocate_spend_unlocked_insufficient_raises(self):
        Balance.objects.create(
            user=self.user,
            amount="50",
            content_type=self.content_type,
            is_locked=False,
        )
        Balance.objects.create(
            user=self.user,
            amount="200",
            content_type=self.content_type,
            is_locked=True,
        )

        with self.assertRaises(ValueError):
            self.user.allocate_spend(Decimal(100))

    def test_allocate_spend_with_locked(self):
        Balance.objects.create(
            user=self.user,
            amount="50",
            content_type=self.content_type,
            is_locked=False,
        )
        Balance.objects.create(
            user=self.user,
            amount="120",
            content_type=self.content_type,
            is_locked=True,
        )

        allocations = self.user.allocate_spend(Decimal(150), allow_locked=True)
        locked_allocs = [a for a in allocations if a["is_locked"]]
        unlocked_allocs = [a for a in allocations if not a["is_locked"]]

        self.assertEqual(len(locked_allocs), 1)
        self.assertEqual(locked_allocs[0]["amount"], Decimal(120))

        self.assertEqual(len(unlocked_allocs), 1)
        self.assertEqual(unlocked_allocs[0]["amount"], Decimal(30))

    def test_allocate_spend_fully_covered_by_locked(self):
        Balance.objects.create(
            user=self.user,
            amount="200",
            content_type=self.content_type,
            is_locked=True,
        )

        allocations = self.user.allocate_spend(Decimal(100), allow_locked=True)
        self.assertEqual(len(allocations), 1)
        self.assertTrue(allocations[0]["is_locked"])
        self.assertEqual(allocations[0]["amount"], Decimal(100))

    def test_allocate_spend_zero_amount(self):
        allocations = self.user.allocate_spend(Decimal(0))
        self.assertEqual(allocations, [])


class UserPromotionalBalanceTests(TestCase):
    def setUp(self):
        self.user = create_user(
            email="promotional@test.com",
            first_name="Promotional",
            last_name="Test",
        )
        self.content_type = ContentType.objects.get_for_model(Paper)

    def _create_balance(self, amount, is_locked=False, lock_type=None):
        return Balance.objects.create(
            user=self.user,
            amount=str(amount),
            content_type=self.content_type,
            is_locked=is_locked,
            lock_type=lock_type,
        )

    def test_locked_balance_without_type_defaults_to_funding_credit(self):
        # Arrange / Act
        balance = self._create_balance("10", is_locked=True)

        # Assert
        self.assertEqual(balance.lock_type, Balance.LockType.FUNDING_CREDIT)

    def test_unlocked_balance_rejects_lock_type(self):
        # Act / Assert
        with self.assertRaisesRegex(
            ValueError, "Unlocked balances cannot have a lock type"
        ):
            self._create_balance(
                "10", is_locked=False, lock_type=Balance.LockType.PROMOTIONAL
            )

    def test_database_rejects_untyped_locked_balance(self):
        # Arrange: bulk_create bypasses Balance.save().
        balance = Balance(
            user=self.user,
            amount="10",
            content_type=self.content_type,
            is_locked=True,
            lock_type=None,
        )

        # Act / Assert
        with self.assertRaises(IntegrityError), transaction.atomic():
            Balance.objects.bulk_create([balance])

    def test_get_promotional_balance_only_sums_promotional_rows(self):
        # Arrange
        self._create_balance("100", is_locked=False)
        self._create_balance("50", is_locked=True)
        self._create_balance(
            "30", is_locked=True, lock_type=Balance.LockType.PROMOTIONAL
        )

        # Act
        promotional = self.user.get_promotional_balance()

        # Assert
        self.assertEqual(promotional, Decimal(30))

    def test_get_funding_credits_balance_excludes_promotional(self):
        # Arrange
        self._create_balance(
            "50", is_locked=True, lock_type=Balance.LockType.FUNDING_CREDIT
        )
        self._create_balance("20", is_locked=True)
        self._create_balance(
            "30", is_locked=True, lock_type=Balance.LockType.PROMOTIONAL
        )

        # Act
        credits = self.user.get_funding_credits_balance()

        # Assert
        self.assertEqual(credits, Decimal(70))

    def test_get_locked_balance_includes_promotional(self):
        # Arrange
        self._create_balance("50", is_locked=True)
        self._create_balance(
            "30", is_locked=True, lock_type=Balance.LockType.PROMOTIONAL
        )

        # Act
        locked = self.user.get_locked_balance()

        # Assert
        self.assertEqual(locked, Decimal(80))

    def test_get_available_balance_excludes_promotional(self):
        # Arrange
        self._create_balance("100", is_locked=False)
        self._create_balance(
            "30", is_locked=True, lock_type=Balance.LockType.PROMOTIONAL
        )

        # Act
        available = self.user.get_available_balance()

        # Assert
        self.assertEqual(available, Decimal(100))

    def test_yield_eligible_lots_include_unlocked_and_promotional(self):
        # Arrange
        self._create_balance("100", is_locked=False)
        self._create_balance(
            "30", is_locked=True, lock_type=Balance.LockType.PROMOTIONAL
        )
        self._create_balance("50", is_locked=True)

        # Act
        lots = self.user.get_yield_eligible_balance_lots_lifo()

        # Assert
        self.assertEqual(
            sorted(lot.amount for lot in lots), [Decimal(30), Decimal(100)]
        )

    def test_yield_eligible_lots_net_pools_separately(self):
        # Arrange: an unlocked debit must not consume the promotional lot,
        # and a promotional debit must not consume the unlocked lot.
        self._create_balance("100", is_locked=False)
        self._create_balance(
            "30", is_locked=True, lock_type=Balance.LockType.PROMOTIONAL
        )
        self._create_balance("-40", is_locked=False)
        self._create_balance(
            "-10", is_locked=True, lock_type=Balance.LockType.PROMOTIONAL
        )

        # Act
        lots = self.user.get_yield_eligible_balance_lots_lifo()

        # Assert
        self.assertEqual(sorted(lot.amount for lot in lots), [Decimal(20), Decimal(60)])

    def test_locked_category_debt_caps_promotional_balance_and_yield(self):
        # Arrange: historical debt in one category must reduce the effective
        # balance of later categories rather than create staking principal.
        self._create_balance(
            "-50", is_locked=True, lock_type=Balance.LockType.FUNDING_CREDIT
        )
        self._create_balance(
            "100", is_locked=True, lock_type=Balance.LockType.PROMOTIONAL
        )

        # Act
        balances = self.user.get_locked_balance_by_lock_type()
        lots = self.user.get_yield_eligible_balance_lots_lifo()

        # Assert
        self.assertEqual(balances[Balance.LockType.FUNDING_CREDIT], Decimal(0))
        self.assertEqual(balances[Balance.LockType.PROMOTIONAL], Decimal(50))
        self.assertEqual(self.user.get_promotional_balance(), Decimal(50))
        self.assertEqual(sum((lot.amount for lot in lots), Decimal(0)), Decimal(50))

    def test_allocate_spend_consumes_promotional_last(self):
        # Arrange
        self._create_balance("50", is_locked=False)
        self._create_balance(
            "40", is_locked=True, lock_type=Balance.LockType.FUNDING_CREDIT
        )
        self._create_balance(
            "500", is_locked=True, lock_type=Balance.LockType.PROMOTIONAL
        )

        # Act
        allocations = self.user.allocate_spend(Decimal(60), allow_locked=True)

        # Assert: non-promotional credits are consumed first, then promotional;
        # each allocation carries its category; unlocked funds are untouched.
        self.assertEqual(len(allocations), 2)
        self.assertTrue(allocations[0]["is_locked"])
        self.assertEqual(allocations[0]["lock_type"], Balance.LockType.FUNDING_CREDIT)
        self.assertEqual(allocations[0]["amount"], Decimal(40))
        self.assertTrue(allocations[1]["is_locked"])
        self.assertEqual(allocations[1]["lock_type"], Balance.LockType.PROMOTIONAL)
        self.assertEqual(allocations[1]["amount"], Decimal(20))

    def test_allocate_locked_spend_splits_by_category_in_order(self):
        # Arrange
        self._create_balance("10", is_locked=True)  # defaults to funding credit
        self._create_balance(
            "20", is_locked=True, lock_type=Balance.LockType.FUNDING_CREDIT
        )
        self._create_balance(
            "30", is_locked=True, lock_type=Balance.LockType.FUNDING_CREDIT
        )
        self._create_balance(
            "500", is_locked=True, lock_type=Balance.LockType.PROMOTIONAL
        )

        # Act
        allocations, remaining = self.user.allocate_locked_spend(Decimal(75))

        # Assert: funding credits are combined, with promotional funds used
        # only for the remainder.
        self.assertEqual(remaining, Decimal(0))
        self.assertEqual(
            [(a["lock_type"], a["amount"]) for a in allocations],
            [
                (Balance.LockType.FUNDING_CREDIT, Decimal(60)),
                (Balance.LockType.PROMOTIONAL, Decimal(15)),
            ],
        )

    def test_allocate_locked_spend_reports_uncovered_remainder(self):
        # Arrange
        self._create_balance(
            "25", is_locked=True, lock_type=Balance.LockType.FUNDING_CREDIT
        )

        # Act
        allocations, remaining = self.user.allocate_locked_spend(Decimal(40))

        # Assert
        self.assertEqual(remaining, Decimal(15))
        self.assertEqual(len(allocations), 1)
        self.assertEqual(allocations[0]["amount"], Decimal(25))

    def test_allocate_spend_promotional_only_locked(self):
        # Arrange
        self._create_balance(
            "500", is_locked=True, lock_type=Balance.LockType.PROMOTIONAL
        )

        # Act
        allocations = self.user.allocate_spend(Decimal(100), allow_locked=True)

        # Assert: the spend is fully covered by promotional funds.
        self.assertEqual(len(allocations), 1)
        self.assertTrue(allocations[0]["is_locked"])
        self.assertEqual(allocations[0]["lock_type"], Balance.LockType.PROMOTIONAL)
        self.assertEqual(allocations[0]["amount"], Decimal(100))


class BalanceLockedByReferralBonusTests(TestCase):
    def setUp(self):
        self.user = create_user(
            email="locked@test.com",
            first_name="Locked",
            last_name="Test",
        )
        self.dist_ct = ContentType.objects.get_for_model(Distribution)
        self.paper_ct = ContentType.objects.get_for_model(Paper)

    def _create_distribution(self, distribution_type="REFERRAL_BONUS", recipient=None):
        return Distribution.objects.create(
            recipient=recipient or self.user,
            amount=100,
            distribution_type=distribution_type,
        )

    def test_returns_locked_referral_bonus_balances(self):
        dist = self._create_distribution()
        Balance.objects.create(
            user=self.user,
            amount="100",
            content_type=self.dist_ct,
            object_id=dist.id,
            is_locked=True,
        )

        result = Balance.locked_by_referral_bonus()
        self.assertEqual(result.count(), 1)
        self.assertEqual(result.first().amount, "100")

    def test_excludes_unlocked_referral_bonus_balances(self):
        dist = self._create_distribution()
        Balance.objects.create(
            user=self.user,
            amount="100",
            content_type=self.dist_ct,
            object_id=dist.id,
            is_locked=False,
        )

        result = Balance.locked_by_referral_bonus()
        self.assertEqual(result.count(), 0)

    def test_excludes_locked_non_referral_distributions(self):
        dist = self._create_distribution(distribution_type="CREATE_BOUNTY")
        Balance.objects.create(
            user=self.user,
            amount="50",
            content_type=self.dist_ct,
            object_id=dist.id,
            is_locked=True,
        )

        result = Balance.locked_by_referral_bonus()
        self.assertEqual(result.count(), 0)

    def test_excludes_locked_non_distribution_balances(self):
        Balance.objects.create(
            user=self.user,
            amount="75",
            content_type=self.paper_ct,
            object_id=1,
            is_locked=True,
        )

        result = Balance.locked_by_referral_bonus()
        self.assertEqual(result.count(), 0)

    def test_filters_within_provided_queryset(self):
        other_user = create_user(
            email="other@test.com",
            first_name="Other",
            last_name="User",
        )
        dist_self = self._create_distribution(recipient=self.user)
        dist_other = self._create_distribution(recipient=other_user)

        Balance.objects.create(
            user=self.user,
            amount="100",
            content_type=self.dist_ct,
            object_id=dist_self.id,
            is_locked=True,
        )
        Balance.objects.create(
            user=other_user,
            amount="200",
            content_type=self.dist_ct,
            object_id=dist_other.id,
            is_locked=True,
        )

        result = Balance.locked_by_referral_bonus(
            Balance.objects.filter(user=self.user)
        )
        self.assertEqual(result.count(), 1)
        self.assertEqual(result.first().amount, "100")

    def test_returns_empty_when_no_matching_balances(self):
        result = Balance.locked_by_referral_bonus()
        self.assertEqual(result.count(), 0)

    def test_multiple_locked_referral_balances(self):
        dist1 = self._create_distribution()
        dist2 = self._create_distribution()

        Balance.objects.create(
            user=self.user,
            amount="100",
            content_type=self.dist_ct,
            object_id=dist1.id,
            is_locked=True,
        )
        Balance.objects.create(
            user=self.user,
            amount="200",
            content_type=self.dist_ct,
            object_id=dist2.id,
            is_locked=True,
        )

        result = Balance.locked_by_referral_bonus()
        self.assertEqual(result.count(), 2)
