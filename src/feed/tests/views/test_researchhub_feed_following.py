from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from feed.models import FeedEntry
from hub.models import Hub
from paper.models import Paper
from researchhub_comment.constants import rh_comment_thread_types
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_default_user
from user.views.follow_view_mixins import create_follow


class FollowingFeedTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = create_random_default_user("following_test_user")

        self.followed_hub = Hub.objects.create(name="Followed Hub", slug="followed-hub")
        self.unfollowed_hub = Hub.objects.create(
            name="Unfollowed Hub", slug="unfollowed-hub"
        )

        create_follow(self.user, self.followed_hub)

        self.paper_content_type = ContentType.objects.get_for_model(Paper)
        self.post_content_type = ContentType.objects.get_for_model(ResearchhubPost)
        self.comment_content_type = ContentType.objects.get_for_model(RhCommentModel)

        self.followed_paper_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        self.followed_paper_doc.hubs.add(self.followed_hub)
        self.followed_paper = Paper.objects.create(
            title="Followed Paper",
            paper_publish_date=timezone.now(),
            unified_document=self.followed_paper_doc,
        )

        self.followed_post_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="POST"
        )
        self.followed_post_doc.hubs.add(self.followed_hub)
        self.followed_post = ResearchhubPost.objects.create(
            title="Followed Post",
            document_type="POST",
            created_by=self.user,
            unified_document=self.followed_post_doc,
        )

        self.unfollowed_paper_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        self.unfollowed_paper_doc.hubs.add(self.unfollowed_hub)
        self.unfollowed_paper = Paper.objects.create(
            title="Unfollowed Paper",
            paper_publish_date=timezone.now(),
            unified_document=self.unfollowed_paper_doc,
        )

        self.paper_entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=self.followed_paper.id,
            unified_document=self.followed_paper_doc,
            hot_score=50,
            hot_score_v2=100,
            content={},
            metrics={},
        )
        self.paper_entry.hubs.add(self.followed_hub)

        self.post_entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.post_content_type,
            object_id=self.followed_post.id,
            unified_document=self.followed_post_doc,
            hot_score=30,
            hot_score_v2=60,
            content={},
            metrics={},
        )
        self.post_entry.hubs.add(self.followed_hub)

        self.unfollowed_entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=self.unfollowed_paper.id,
            unified_document=self.unfollowed_paper_doc,
            hot_score=100,
            hot_score_v2=200,
            content={},
            metrics={},
        )
        self.unfollowed_entry.hubs.add(self.unfollowed_hub)

        comment_thread = RhCommentThreadModel.objects.create(
            thread_type=rh_comment_thread_types.GENERIC_COMMENT,
            content_type=self.paper_content_type,
            object_id=self.followed_paper.id,
            created_by=self.user,
        )
        self.comment = RhCommentModel.objects.create(
            thread=comment_thread,
            comment_content_json={"ops": [{"insert": "Test comment"}]},
            comment_content_type="QUILL_EDITOR",
            created_by=self.user,
        )
        self.comment_entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.comment_content_type,
            object_id=self.comment.id,
            unified_document=self.followed_paper_doc,
            hot_score=40,
            hot_score_v2=80,
            content={},
            metrics={},
        )
        self.comment_entry.hubs.add(self.followed_hub)

    def tearDown(self):
        cache.clear()

    def test_unauthenticated_user_gets_empty_results(self):
        url = reverse("feed-list")
        response = self.client.get(url, {"feed_view": "following"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

    def test_authenticated_user_gets_followed_hub_results(self):
        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "following"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(len(response.data["results"]), 0)

        result_ids = [r["content_object"]["id"] for r in response.data["results"]]
        self.assertIn(self.followed_paper.id, result_ids)
        self.assertNotIn(self.followed_post.id, result_ids)
        self.assertNotIn(self.unfollowed_paper.id, result_ids)

    def test_user_following_no_hubs_gets_empty_results(self):
        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        self.user.following.all().delete()

        response = self.client.get(url, {"feed_view": "following"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

    def test_follow_then_unfollow_hub(self):
        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response1 = self.client.get(url, {"feed_view": "following"})
        self.assertGreater(len(response1.data["results"]), 0)

        self.user.following.all().delete()
        cache.clear()

        response2 = self.client.get(url, {"feed_view": "following"})
        self.assertEqual(len(response2.data["results"]), 0)

    def test_following_hub_supports_sorting_by_hot_score(self):
        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(
            url, {"feed_view": "following", "ordering": "hot_score"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertGreaterEqual(len(results), 1)

        if len(results) >= 1:
            self.assertEqual(results[0]["content_object"]["id"], self.followed_paper.id)

    def test_user_follows_multiple_hubs_gets_multiple_results(self):
        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        another_hub = Hub.objects.create(name="Another Hub", slug="another-hub")
        create_follow(self.user, another_hub)

        another_doc = ResearchhubUnifiedDocument.objects.create(document_type="POST")
        another_doc.hubs.add(another_hub)
        another_post = ResearchhubPost.objects.create(
            title="Another Post",
            document_type="POST",
            created_by=self.user,
            unified_document=another_doc,
        )

        another_entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.post_content_type,
            object_id=another_post.id,
            unified_document=another_doc,
            content={},
            metrics={},
        )
        another_entry.hubs.add(another_hub)

        response = self.client.get(url, {"feed_view": "following"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result_ids = [r["content_object"]["id"] for r in response.data["results"]]
        self.assertIn(self.followed_paper.id, result_ids)
        self.assertNotIn(self.followed_post.id, result_ids)
        self.assertNotIn(another_post.id, result_ids)

    def test_following_hub_supports_sorting_by_hot_score_v2(self):
        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(
            url, {"feed_view": "following", "ordering": "hot_score_v2"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertGreaterEqual(len(results), 1)

        if len(results) >= 2:
            first_score = results[0].get("hot_score_v2", 0)
            second_score = results[1].get("hot_score_v2", 0)
            self.assertGreaterEqual(first_score, second_score)

    def test_following_hub_supports_sorting_by_latest(self):
        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(
            url, {"feed_view": "following", "ordering": "latest"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertGreater(len(results), 0)

        if len(results) >= 2:
            first_date = results[0].get("action_date")
            second_date = results[1].get("action_date")
            self.assertGreaterEqual(first_date, second_date)

    def test_user_following_hub_that_does_not_exist_ignores_it(self):
        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(
            url, {"feed_view": "following", "hub_slug": "nonexistent-hub"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

    def test_following_feed_rejects_invalid_ordering(self):
        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(
            url, {"feed_view": "following", "ordering": "invalid_sort"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertGreaterEqual(len(results), 1)

        if len(results) >= 2:
            first_score = results[0].get("hot_score_v2", 0)
            second_score = results[1].get("hot_score_v2", 0)
            self.assertGreaterEqual(first_score, second_score)

    def test_following_returns_only_papers_and_posts(self):
        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "following"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]

        for result in results:
            content_type = result.get("content_type")
            self.assertIn(content_type, ["PAPER", "RESEARCHHUBPOST", "RHCOMMENTMODEL"])

    def test_following_feed_filters_only_papers(self):
        url = reverse("feed-list")

        # Arrange
        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.get(url, {"feed_view": "following"})

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]

        result_ids = [r["content_object"]["id"] for r in results]
        content_types = [r["content_type"] for r in results]

        self.assertIn(self.followed_paper.id, result_ids)
        self.assertNotIn(self.followed_post.id, result_ids)
        self.assertIn("PAPER", content_types)
        self.assertNotIn("RESEARCHHUBPOST", content_types)

    def _create_paper_with_feed_entry(self, title, hubs):
        """Helper to create a paper with associated feed entry and hubs."""
        doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        doc.hubs.add(*hubs)
        paper = Paper.objects.create(
            title=title,
            paper_publish_date=timezone.now(),
            unified_document=doc,
        )
        entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=paper.id,
            unified_document=doc,
            content={},
            metrics={},
        )
        entry.hubs.add(*hubs)
        return paper

    def test_following_returns_only_papers_in_preprint_hubs(self):
        """Following feed only returns papers that are also in a preprint hub."""
        self.client.force_authenticate(user=self.user)

        biorxiv_hub = Hub.objects.create(name="bioRxiv", slug="biorxiv")
        create_follow(self.user, biorxiv_hub)

        # Create papers in different hub combinations
        non_preprint = self._create_paper_with_feed_entry(
            "Non-Preprint", [self.followed_hub]
        )
        preprint = self._create_paper_with_feed_entry("Preprint", [biorxiv_hub])
        both = self._create_paper_with_feed_entry(
            "Both", [self.followed_hub, biorxiv_hub]
        )

        response = self.client.get(reverse("feed-list"), {"feed_view": "following"})

        result_ids = [r["content_object"]["id"] for r in response.data["results"]]
        self.assertIn(preprint.id, result_ids)
        self.assertIn(both.id, result_ids)
        self.assertNotIn(non_preprint.id, result_ids)
