from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from feed.models import FeedEntry, HiddenFeedEntry
from hub.models import Hub
from paper.models import Paper
from researchhub_comment.constants.rh_comment_thread_types import GENERIC_COMMENT
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PAPER,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_default_user
from user.views.follow_view_mixins import create_follow
from utils.test_helpers import AWSMockTestCase


def _feed_entry_ids(response):
    return {item["id"] for item in response.data["results"]}


def _unified_document_ids(response):
    ids = set()
    for item in response.data["results"]:
        doc_id = item.get("unified_document_id")
        if doc_id is None:
            content_object = item.get("content_object") or {}
            doc_id = content_object.get("unified_document_id")
        if doc_id is not None:
            ids.add(doc_id)
    return ids


class ExcludedInFeedVisibilityTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.warm_patcher = patch(
            "feed.services.feed_entry_visibility_service."
            "FeedEntryVisibilityService._queue_activity_feed_cache_warm"
        )
        self.mock_warm = self.warm_patcher.start()
        self.on_commit_patcher = patch(
            "feed.services.feed_entry_visibility_service.transaction.on_commit",
            side_effect=lambda func, **kwargs: func(),
        )
        self.on_commit_patcher.start()
        self.addCleanup(self.warm_patcher.stop)
        self.addCleanup(self.on_commit_patcher.stop)

        self.client = APIClient()
        self.user = create_random_default_user("excluded_feed_user")
        self.moderator = create_random_default_user("excluded_feed_mod", moderator=True)
        self.hub, _ = Hub.objects.get_or_create(
            slug="biorxiv", defaults={"name": "bioRxiv"}
        )
        create_follow(self.user, self.hub)
        self.paper_content_type = ContentType.objects.get_for_model(Paper)
        self.post_content_type = ContentType.objects.get_for_model(ResearchhubPost)

        self.visible_paper_doc, self.visible_paper, self.visible_paper_entry = (
            self._create_paper("Visible Paper")
        )
        self.hidden_paper_doc, self.hidden_paper, self.hidden_paper_entry = (
            self._create_paper("Hidden Paper")
        )
        self._hide_feed_entry(self.hidden_paper_entry)

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def _create_paper(self, title):
        unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=PAPER
        )
        unified_document.hubs.add(self.hub)
        paper = Paper.objects.create(
            title=title,
            paper_publish_date=timezone.now(),
            uploaded_by=self.user,
            is_public=True,
            is_removed=False,
            unified_document=unified_document,
        )
        entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=paper.id,
            unified_document=unified_document,
            hot_score=50,
            hot_score_v2=50,
            content={},
            metrics={},
            pdf_copyright_allows_display=True,
        )
        entry.hubs.add(self.hub)
        return unified_document, paper, entry

    def _hide_feed_entry(self, feed_entry):
        HiddenFeedEntry.objects.get_or_create(
            feed_entry=feed_entry,
            defaults={"hidden_by": self.moderator},
        )
        cache.clear()

    def _exclude_url(self, feed_entry_id):
        return f"/api/activity_feed/{feed_entry_id}/exclude_from_feed/"

    def _include_url(self, feed_entry_id):
        return f"/api/activity_feed/{feed_entry_id}/include_in_feed/"

    def test_hidden_paper_is_omitted_from_popular_latest_and_following_feeds(self):
        # Arrange
        self.client.force_authenticate(self.user)
        cases = [
            {"feed_view": "popular", "ordering": "hot_score_v2"},
            {"feed_view": "latest"},
            {"feed_view": "following"},
        ]

        # Act / Assert
        for params in cases:
            response = self.client.get(reverse("feed-list"), params)
            self.assertEqual(response.status_code, status.HTTP_200_OK, params)
            ids = _unified_document_ids(response)
            self.assertIn(self.visible_paper_doc.id, ids, params)
            self.assertNotIn(self.hidden_paper_doc.id, ids, params)

    def test_hidden_paper_remains_directly_retrievable(self):
        # Act
        paper_response = self.client.get(f"/api/paper/{self.hidden_paper.id}/")
        metadata_response = self.client.get(
            f"/api/researchhub_unified_document/{self.hidden_paper_doc.id}"
            "/get_document_metadata/"
        )

        # Assert
        self.assertEqual(paper_response.status_code, status.HTTP_200_OK)
        self.assertEqual(paper_response.data["id"], self.hidden_paper.id)
        self.assertEqual(metadata_response.status_code, status.HTTP_200_OK)
        self.assertEqual(metadata_response.data["id"], self.hidden_paper_doc.id)
        self.assertTrue(
            FeedEntry.objects.filter(pk=self.hidden_paper_entry.pk).exists()
        )

    def test_hiding_one_activity_entry_leaves_siblings_visible(self):
        # Arrange
        proposal = create_post(
            created_by=self.user,
            document_type=PREREGISTRATION,
            title="Proposal With Comment",
        )
        post_entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.post_content_type,
            object_id=proposal.id,
            unified_document=proposal.unified_document,
            user=self.user,
            content={},
            metrics={},
        )
        thread = RhCommentThreadModel.objects.create(
            thread_type=GENERIC_COMMENT,
            content_type=self.post_content_type,
            object_id=proposal.id,
            created_by=self.user,
        )
        comment = RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "Noisy comment"}]},
            comment_type=GENERIC_COMMENT,
            created_by=self.user,
            thread=thread,
        )
        comment_entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=comment.id,
            unified_document=proposal.unified_document,
            user=self.user,
            content={},
            metrics={},
        )
        self._hide_feed_entry(comment_entry)

        # Act
        response = self.client.get(reverse("activity_feed-list"))

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = _feed_entry_ids(response)
        self.assertIn(post_entry.id, ids)
        self.assertNotIn(comment_entry.id, ids)

    def test_moderator_exclude_and_include_via_api(self):
        # Arrange
        self.client.force_authenticate(self.moderator)
        entry = self.visible_paper_entry

        # Act / Assert
        exclude_response = self.client.post(self._exclude_url(entry.id))
        self.assertEqual(exclude_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            exclude_response.data,
            {"id": entry.id, "is_excluded_in_feed": True},
        )
        self.assertTrue(HiddenFeedEntry.objects.filter(feed_entry=entry).exists())
        self.mock_warm.assert_called()

        include_response = self.client.post(self._include_url(entry.id))
        self.assertEqual(include_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            include_response.data,
            {"id": entry.id, "is_excluded_in_feed": False},
        )
        self.assertFalse(HiddenFeedEntry.objects.filter(feed_entry=entry).exists())

    def test_exclude_and_include_are_idempotent(self):
        # Arrange
        self.client.force_authenticate(self.moderator)
        entry = self.visible_paper_entry

        # Act / Assert
        first = self.client.post(self._exclude_url(entry.id))
        second = self.client.post(self._exclude_url(entry.id))
        self.assertEqual(first.data, second.data)

        self.client.post(self._exclude_url(entry.id))
        included_once = self.client.post(self._include_url(entry.id))
        included_twice = self.client.post(self._include_url(entry.id))
        self.assertEqual(included_once.data, included_twice.data)

    def test_non_moderator_cannot_toggle_visibility(self):
        # Arrange
        self.client.force_authenticate(self.user)
        entry = self.visible_paper_entry

        # Act
        exclude_response = self.client.post(self._exclude_url(entry.id))
        include_response = self.client.post(self._include_url(entry.id))

        # Assert
        self.assertEqual(exclude_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(include_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(HiddenFeedEntry.objects.filter(feed_entry=entry).exists())
        self.mock_warm.assert_not_called()

    def test_excluded_list_returns_feed_entry_payload(self):
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.get("/api/activity_feed/excluded_from_feed/")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        listed_ids = [row["id"] for row in response.data["results"]]
        self.assertIn(self.hidden_paper_entry.id, listed_ids)
        hidden_row = next(
            row
            for row in response.data["results"]
            if row["id"] == self.hidden_paper_entry.id
        )
        self.assertIn("content_object", hidden_row)
        self.assertIn("related_work", hidden_row)

    def test_pending_moderation_queue_is_unchanged(self):
        # Arrange
        pending = create_post(
            created_by=self.user,
            document_type=PREREGISTRATION,
            title="Pending proposal",
        )
        pending.unified_document.status = ResearchhubUnifiedDocument.PENDING
        pending.unified_document.save(update_fields=["status"])
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.get(
            reverse("moderator_feed-pending-moderation"),
            {"content_type": "PREREGISTRATION"},
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        post_ids = [item["content_object"]["id"] for item in response.data["results"]]
        self.assertIn(pending.id, post_ids)

    def test_hide_enqueues_activity_feed_cache_warm(self):
        # Arrange
        self.client.force_authenticate(self.moderator)
        entry = self.visible_paper_entry
        self.mock_warm.reset_mock()

        # Act
        self.client.post(self._exclude_url(entry.id))

        # Assert
        self.mock_warm.assert_called_once()
