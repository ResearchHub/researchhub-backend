import json
import time

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from discussion.models import Vote as GrmVote
from hub.models import Hub
from paper.related_models.authorship_model import Authorship
from paper.related_models.paper_model import Paper
from reputation.distributions import Distribution as Dist
from reputation.distributor import Distributor
from reputation.models import Distribution, Score
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from user.models import UserVerification
from user.serializers import (
    AuthorSerializer,
    DynamicAuthorProfileSerializer,
    UserEditableSerializer,
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
                proof_item_content_type=ContentType.objects.get_for_model(GrmVote),
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
        self.user.is_verified = True
        serializer = UserEditableSerializer(self.user)
        self.assertTrue(serializer.data["is_verified"])

    def test_user_serializer_is_not_verified(self):
        self.user.is_verified = False
        serializer = UserEditableSerializer(self.user)
        self.assertFalse(serializer.data["is_verified"])

    def test_user_serializer_is_verified_v2(self):
        UserVerification.objects.create(
            user=self.user,
            status=UserVerification.Status.APPROVED,
        )
        serializer = UserEditableSerializer(self.user)
        self.assertTrue(serializer.data["is_verified_v2"])

    def test_user_serializer_is_not_verified_v2(self):
        UserVerification.objects.create(
            user=self.user,
            status=UserVerification.Status.DECLINED,
        )
        serializer = UserEditableSerializer(self.user)
        self.assertFalse(serializer.data["is_verified_v2"])

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
            },
        )
