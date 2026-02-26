import json
import time

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from discussion.models import Vote
from hub.models import Hub
from paper.related_models.authorship_model import Authorship
from paper.related_models.paper_model import Paper
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.distributions import Distribution as Dist
from reputation.distributor import Distributor
from reputation.models import Distribution, Score
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from user.models import UserVerification
from user.serializers import (
    AuthorSerializer,
    DynamicAuthorProfileSerializer,
    DynamicUserSerializer,
    UserEditableSerializer,
    UserSerializer,
)
from user.tests.helpers import create_university, create_user


class UserSerializersTests(TestCase):
    def setUp(self):
        self.user = create_user(first_name="Serializ")

        distribution = Dist("REWARD", 1000000000, give_rep=False)

        distributor = Distributor(
            distribution, self.user, self.user, time.time(), self.user
        )
        distributor.distribute()

        self.university = create_university()
        paper1 = Paper.objects.create(
            title="title1",
            citations=10,
        )
        paper2 = Paper.objects.create(
            title="title2",
            citations=20,
        )
        Authorship.objects.create(author=self.user.author_profile, paper=paper1)
        Authorship.objects.create(author=self.user.author_profile, paper=paper2)

        self.user_without_papers = create_user(email="email1@researchhub.com")

        for i in range(50):
            Distribution.objects.create(
                recipient=self.user,
                proof_item_content_type=ContentType.objects.get_for_model(Vote),
                reputation_amount=1,
            )
            thread = RhCommentThreadModel.objects.create(
                object_id=paper1.id,
                content_type=ContentType.objects.get_for_model(Paper),
                created_by=self.user,
            )

            RhCommentModel.objects.create(
                created_by=self.user,
                comment_type="REVIEW",
                is_removed=False,
                thread_id=thread.id,
            )

    def test_author_serializer_succeeds_without_user_or_university(self):
        data = {
            "first_name": "Ray",
            "last_name": "Man",
        }
        serializer = AuthorSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_author_serializer_without_orcid_sends_null(self):
        serializer = AuthorSerializer(self.user.author_profile)
        json_data = json.dumps(serializer.data)
        self.assertIn('"orcid_id": null', json_data)

    def test_author_serializer_with_reputation(self):
        hub1 = Hub.objects.create(name="Hub 1")
        hub2 = Hub.objects.create(name="Hub 2")
        Score.objects.create(
            author=self.user.author_profile,
            hub=hub1,
            score=900,
        )

        Score.objects.create(
            author=self.user.author_profile,
            hub=hub2,
            score=1000,
        )

        serializer = AuthorSerializer(self.user.author_profile)
        self.assertEqual(serializer.data["reputation_v2"]["score"], 1000)
        self.assertEqual(serializer.data["reputation_list"][0]["score"], 1000)
        self.assertEqual(serializer.data["reputation_list"][1]["score"], 900)

    def test_user_serializer_is_verified(self):
        # Arrange
        UserVerification.objects.create(
            user=self.user,
            status=UserVerification.Status.APPROVED,
        )

        # Act
        serializer = UserEditableSerializer(self.user)

        # Assert
        self.assertTrue(serializer.data["is_verified"])

    def test_user_serializer_is_not_verified(self):
        # Arrange
        UserVerification.objects.create(
            user=self.user,
            status=UserVerification.Status.DECLINED,
        )

        # Act
        serializer = UserEditableSerializer(self.user)

        # Assert
        self.assertFalse(serializer.data["is_verified"])

    def test_dynamic_author_serializer_headline(self):
        # Arrange
        self.user.author_profile.headline = "headline1"

        # Act
        serializer = DynamicAuthorProfileSerializer(self.user.author_profile)

        # Assert
        self.assertEqual(serializer.data["headline"], "headline1")

    def test_dynamic_author_serializer_headline_without_headline_and_topics(self):
        # Act
        serializer = DynamicAuthorProfileSerializer(self.user.author_profile)

        # Assert
        self.assertIsNone(serializer.data["headline"])

    def test_dynamic_author_serializer_summary_stats(self):
        # Act
        serializer = DynamicAuthorProfileSerializer(self.user.author_profile)

        # Assert
        self.assertEqual(
            serializer.data["summary_stats"],
            {
                "amount_funded": 0,
                "citation_count": 30,
                "peer_review_count": 50,
                "two_year_mean_citedness": 0,
                "upvote_count": 50,
                "works_count": 2,
                "open_access_pct": 0.0,
            },
        )

    def test_dynamic_author_serializer_summary_stats_without_papers(self):
        # Act
        serializer = DynamicAuthorProfileSerializer(
            self.user_without_papers.author_profile
        )

        # Assert
        self.assertEqual(
            serializer.data["summary_stats"],
            {
                "amount_funded": 0,
                "citation_count": 0,
                "peer_review_count": 0,
                "two_year_mean_citedness": 0,
                "upvote_count": 0,
                "works_count": 0,
                "open_access_pct": 0.0,
            },
        )


class UserBalancesSerializerTests(TestCase):
    def setUp(self):
        self.user = create_user(first_name="BalanceTest")
        self.other_user = create_user(email="other@researchhub.com")

        # Create exchange rate: 1 RSC = 0.5 USD (or 1 USD = 2 RSC)
        RscExchangeRate.objects.create(rate=0.5, real_rate=0.5)

        # Give user some RSC balance
        distribution = Dist("REWARD", 1000, give_rep=False)
        distributor = Distributor(
            distribution, self.user, self.user, time.time(), self.user
        )
        distributor.distribute()

    def test_user_serializer_balances_returns_for_own_user(self):
        """UserSerializer should return balances when user views own profile"""
        serializer = UserSerializer(
            self.user,
            context={"user": self.user},
        )
        # Set read_only to False to enable balance display
        serializer.read_only = False

        balances = serializer.data["balances"]

        self.assertIsNotNone(balances)
        self.assertEqual(balances["rsc"], 1000)
        self.assertEqual(balances["rsc_locked"], 0)
        self.assertEqual(balances["total_rsc"], 1000)
        # total_usd_cents = 1000 RSC * 0.5 rate * 100 = 50000
        self.assertEqual(balances["total_usd_cents"], 50000)

    def test_user_serializer_balances_returns_none_for_other_user(self):
        """UserSerializer should return None for balances when viewing another user"""
        serializer = UserSerializer(
            self.user,
            context={"user": self.other_user},
        )
        serializer.read_only = False

        self.assertIsNone(serializer.data["balances"])

    def test_user_serializer_balance_backwards_compatible(self):
        """UserSerializer should still return top-level balance for backwards compatibility"""
        serializer = UserSerializer(
            self.user,
            context={"user": self.user},
        )
        serializer.read_only = False

        self.assertEqual(serializer.data["balance"], 1000)

    def test_user_editable_serializer_balances_returns_for_own_user(self):
        """UserEditableSerializer should return balances when user views own profile"""
        serializer = UserEditableSerializer(
            self.user,
            context={"user": self.user},
        )

        balances = serializer.data["balances"]

        self.assertIsNotNone(balances)
        self.assertEqual(balances["rsc"], 1000)
        self.assertEqual(balances["rsc_locked"], 0)
        self.assertEqual(balances["total_rsc"], 1000)
        self.assertEqual(balances["total_usd_cents"], 50000)

    def test_user_editable_serializer_balances_returns_none_for_other_user(self):
        """UserEditableSerializer should return None for balances when viewing another user"""
        serializer = UserEditableSerializer(
            self.user,
            context={"user": self.other_user},
        )

        self.assertIsNone(serializer.data["balances"])

    def test_user_editable_serializer_backwards_compatible(self):
        """UserEditableSerializer should still return top-level balance and locked_balance"""
        serializer = UserEditableSerializer(
            self.user,
            context={"user": self.user},
        )

        self.assertEqual(serializer.data["balance"], 1000)
        self.assertEqual(serializer.data["locked_balance"], 0)

    def test_dynamic_user_serializer_balances_returns_for_own_user(self):
        """DynamicUserSerializer should return balances when user views own profile"""
        serializer = DynamicUserSerializer(
            self.user,
            context={"user": self.user},
        )

        balances = serializer.data["balances"]

        self.assertIsNotNone(balances)
        self.assertEqual(balances["rsc"], 1000)
        self.assertEqual(balances["rsc_locked"], 0)
        self.assertEqual(balances["total_rsc"], 1000)
        self.assertEqual(balances["total_usd_cents"], 50000)

    def test_dynamic_user_serializer_balances_returns_none_for_other_user(self):
        """DynamicUserSerializer should return None for balances when viewing another user"""
        serializer = DynamicUserSerializer(
            self.user,
            context={"user": self.other_user},
        )

        self.assertIsNone(serializer.data["balances"])

    def test_balances_with_locked_rsc(self):
        """Balances should include locked RSC in totals"""
        # Lock some RSC for the user
        from purchase.models import Balance

        Balance.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(Distribution),
            object_id=1,
            amount=200,
            is_locked=True,
        )

        serializer = UserEditableSerializer(
            self.user,
            context={"user": self.user},
        )

        balances = serializer.data["balances"]

        self.assertEqual(balances["rsc"], 1000)
        self.assertEqual(balances["rsc_locked"], 200)
        # total_rsc = 1200 RSC
        self.assertEqual(balances["total_rsc"], 1200)
        # total_usd_cents = 1200 RSC * 0.5 * 100 = 60000
        self.assertEqual(balances["total_usd_cents"], 60000)

    def test_balances_with_zero_balances(self):
        """Balances should work correctly with zero balances"""
        new_user = create_user(email="newuser@researchhub.com")

        serializer = UserEditableSerializer(
            new_user,
            context={"user": new_user},
        )

        balances = serializer.data["balances"]

        self.assertIsNotNone(balances)
        self.assertEqual(balances["rsc"], 0)
        self.assertEqual(balances["rsc_locked"], 0)
        self.assertEqual(balances["total_rsc"], 0)
        self.assertEqual(balances["total_usd_cents"], 0)
