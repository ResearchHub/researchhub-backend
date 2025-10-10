"""Tests for improved comment sorting with quality factors."""

from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APITestCase

from discussion.models import Vote
from purchase.models import Purchase
from researchhub_comment.models import RhCommentModel
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (  # noqa: E501
    ResearchhubUnifiedDocument,
)
from user.related_models.user_verification_model import UserVerification
from user.tests.helpers import create_random_authenticated_user, create_user


class QualityScoreSortingTests(APITestCase):
    def setUp(self):
        # Create a post to attach comments to
        self.moderator = create_user(email="moderator@researchhub.com", moderator=True)
        self.post_creator = create_random_authenticated_user("post_creator")

        unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION",
        )
        self.post = ResearchhubPost.objects.create(
            created_by=self.post_creator,
            renderable_text="Test post for comment sorting",
            title="Test Post",
            document_type="DISCUSSION",
            unified_document=unified_document,
        )

        # Create various types of users
        self.regular_user = self._create_user_with_reputation("regular@test.com", 100)
        self.verified_user = self._create_verified_user("verified@test.com", 100)
        self.high_rep_user = self._create_user_with_reputation("highrep@test.com", 5000)
        self.verified_high_rep_user = self._create_verified_user(
            "verified_highrep@test.com", 5000
        )
        self.spammer = create_user(email="spammer@test.com")
        self.spammer.probable_spammer = True
        self.spammer.save()

    def _create_user_with_reputation(self, email, reputation):
        user = create_user(email=email)
        user.reputation = reputation
        user.save()
        return user

    def _create_verified_user(self, email, reputation):
        user = self._create_user_with_reputation(email, reputation)
        UserVerification.objects.create(
            user=user,
            first_name="Verified",
            last_name="User",
            status=UserVerification.Status.APPROVED,
            verified_by=UserVerification.Type.PERSONA,
            external_id="test_id",
        )
        return user

    def _create_comment(self, user, text="Test comment"):
        self.client.force_authenticate(user)
        response = self.client.post(
            f"/api/researchhubpost/{self.post.id}/comments/create_rh_comment/",
            {
                "comment_content_json": {"ops": [{"insert": text}]},
                "comment_content_type": "QUILL_EDITOR",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        return RhCommentModel.objects.get(id=response.data["id"])

    def _add_upvote(self, comment, voter):
        # Skip if voter is the comment creator (auto-upvoted on creation)
        if voter == comment.created_by:
            return

        content_type = ContentType.objects.get_for_model(RhCommentModel)
        vote, created = Vote.objects.get_or_create(
            created_by=voter,
            content_type=content_type,
            object_id=comment.id,
            defaults={"vote_type": Vote.UPVOTE},
        )
        if created:
            comment.score += 1
            comment.save()

    def _add_tip(self, comment, tipper, amount):
        content_type = ContentType.objects.get_for_model(RhCommentModel)
        Purchase.objects.create(
            user=tipper,
            content_type=content_type,
            object_id=comment.id,
            amount=str(amount),
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.BOOST,
            paid_status=Purchase.PAID,
        )

    def test_removed_comments_appear_at_bottom(self):
        # Create two comments
        good_comment = self._create_comment(self.regular_user, "Good comment")
        bad_comment = self._create_comment(self.regular_user, "Bad comment")

        # Give the bad comment a lot of upvotes
        for _ in range(10):
            voter = create_random_authenticated_user(f"voter_{_}")
            self._add_upvote(bad_comment, voter)

        # Give the good comment just 1 upvote
        self._add_upvote(good_comment, self.regular_user)

        # Remove/censor the bad comment
        self.client.force_authenticate(self.moderator)
        censor_response = self.client.delete(
            f"/api/researchhubpost/{self.post.id}/comments/{bad_comment.id}/censor/"
        )
        self.assertEqual(censor_response.status_code, 200)

        # Fetch comments with BEST sorting
        self.client.force_authenticate(self.regular_user)
        response = self.client.get(
            f"/api/researchhubpost/{self.post.id}/comments/",
            {
                "ordering": "BEST",
                "privacy_type": "PUBLIC",
                "parent__isnull": "true",
            },
        )

        self.assertEqual(response.status_code, 200)
        results = response.data["results"]

        # The good comment should appear first, removed comment last
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["id"], good_comment.id)
        self.assertEqual(results[1]["id"], bad_comment.id)
        self.assertTrue(results[1]["is_removed"])

    def test_verified_user_comments_ranked_higher(self):
        # Create comments with same number of upvotes
        regular_comment = self._create_comment(self.regular_user, "Regular comment")
        verified_comment = self._create_comment(self.verified_user, "Verified comment")

        # Give both 5 upvotes from regular users
        for i in range(5):
            voter = create_random_authenticated_user(f"voter_{i}")
            self._add_upvote(regular_comment, voter)
            self._add_upvote(verified_comment, voter)

        # Fetch with BEST sorting
        response = self.client.get(
            f"/api/researchhubpost/{self.post.id}/comments/",
            {
                "ordering": "BEST",
                "privacy_type": "PUBLIC",
                "parent__isnull": "true",
            },
        )

        results = response.data["results"]

        # Verified user's comment should rank higher
        self.assertEqual(results[0]["id"], verified_comment.id)
        self.assertEqual(results[1]["id"], regular_comment.id)

    def test_tips_boost_comment_ranking(self):
        # Create two comments with same upvotes
        no_tip_comment = self._create_comment(self.regular_user, "No tip comment")
        tipped_comment = self._create_comment(self.regular_user, "Tipped comment")

        # Give both 3 upvotes
        for i in range(3):
            voter = create_random_authenticated_user(f"voter_{i}")
            self._add_upvote(no_tip_comment, voter)
            self._add_upvote(tipped_comment, voter)

        # Add a tip to the second comment
        tipper = create_random_authenticated_user("tipper")
        self._add_tip(tipped_comment, tipper, Decimal("100.00"))

        # Fetch with BEST sorting
        response = self.client.get(
            f"/api/researchhubpost/{self.post.id}/comments/",
            {
                "ordering": "BEST",
                "privacy_type": "PUBLIC",
                "parent__isnull": "true",
            },
        )

        results = response.data["results"]

        # Tipped comment should rank higher
        self.assertEqual(results[0]["id"], tipped_comment.id)
        self.assertEqual(results[1]["id"], no_tip_comment.id)

    def test_high_reputation_users_get_boost(self):
        # Create comments with same upvotes
        low_rep_comment = self._create_comment(self.regular_user, "Low rep")
        high_rep_comment = self._create_comment(self.high_rep_user, "High rep")

        # Give both 2 upvotes
        for i in range(2):
            voter = create_random_authenticated_user(f"voter_{i}")
            self._add_upvote(low_rep_comment, voter)
            self._add_upvote(high_rep_comment, voter)

        # Fetch with BEST sorting
        response = self.client.get(
            f"/api/researchhubpost/{self.post.id}/comments/",
            {
                "ordering": "BEST",
                "privacy_type": "PUBLIC",
                "parent__isnull": "true",
            },
        )

        results = response.data["results"]

        # High reputation user's comment should rank higher
        self.assertEqual(results[0]["id"], high_rep_comment.id)
        self.assertEqual(results[1]["id"], low_rep_comment.id)

    def test_spammer_votes_filtered_out(self):
        # Create two comments
        legit_comment = self._create_comment(self.regular_user, "Legit comment")
        spam_boosted_comment = self._create_comment(self.regular_user, "Spam boosted")

        # Give legit comment 2 upvotes from regular users
        for i in range(2):
            voter = create_random_authenticated_user(f"voter_{i}")
            self._add_upvote(legit_comment, voter)

        # Give spam boosted comment 1 legit upvote and 10 spammer upvotes
        legit_voter = create_random_authenticated_user("legit_voter")
        self._add_upvote(spam_boosted_comment, legit_voter)

        # Add spammer votes (these should be filtered out)
        # Create multiple spammer accounts to simulate spam voting
        content_type = ContentType.objects.get_for_model(RhCommentModel)
        for i in range(10):
            spammer = create_user(email=f"spammer{i}@test.com")
            spammer.probable_spammer = True
            spammer.save()
            Vote.objects.create(
                created_by=spammer,
                content_type=content_type,
                object_id=spam_boosted_comment.id,
                vote_type=Vote.UPVOTE,
            )

        # Fetch with BEST sorting
        response = self.client.get(
            f"/api/researchhubpost/{self.post.id}/comments/",
            {
                "ordering": "BEST",
                "privacy_type": "PUBLIC",
                "parent__isnull": "true",
            },
        )

        results = response.data["results"]

        # Legit comment should rank higher despite spam boosted
        # (because spammer votes are filtered out in quality score)
        self.assertEqual(results[0]["id"], legit_comment.id)
        self.assertEqual(results[1]["id"], spam_boosted_comment.id)

    def test_combined_factors_ranking(self):
        # Comment 1: Regular user, no tips, few upvotes
        comment1 = self._create_comment(self.regular_user, "Basic comment")
        self._add_upvote(comment1, create_random_authenticated_user("v1"))

        # Comment 2: Verified high rep user, no tips, few upvotes
        comment2 = self._create_comment(self.verified_high_rep_user, "Quality comment")
        self._add_upvote(comment2, create_random_authenticated_user("v2"))

        # Comment 3: Regular user with tips and upvotes
        comment3 = self._create_comment(self.regular_user, "Tipped comment")
        for i in range(3):
            voter = create_random_authenticated_user(f"v3_{i}")
            self._add_upvote(comment3, voter)
        tipper = create_random_authenticated_user("t1")
        self._add_tip(comment3, tipper, Decimal("50.00"))

        # Comment 4: High upvotes but removed
        comment4 = self._create_comment(self.regular_user, "Removed comment")
        for i in range(10):
            self._add_upvote(comment4, create_random_authenticated_user(f"v4_{i}"))
        comment4.is_removed = True
        comment4.save()

        # Fetch with BEST sorting
        response = self.client.get(
            f"/api/researchhubpost/{self.post.id}/comments/",
            {
                "ordering": "BEST",
                "privacy_type": "PUBLIC",
                "parent__isnull": "true",
            },
        )

        results = response.data["results"]
        result_ids = [r["id"] for r in results]

        # Expected order:
        # 1. comment3 (tipped + upvotes)
        # 2. comment2 (verified + high rep)
        # 3. comment1 (basic)
        # 4. comment4 (removed, should be last despite high votes)
        self.assertEqual(len(results), 4)
        self.assertEqual(result_ids[0], comment3.id)
        self.assertEqual(result_ids[1], comment2.id)
        self.assertEqual(result_ids[2], comment1.id)
        self.assertEqual(result_ids[3], comment4.id)
