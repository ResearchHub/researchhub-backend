from unittest.mock import Mock

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from feed.models import FeedEntry
from paper.tests.helpers import create_paper
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import GRANT
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from researchhub_document.services.unified_document_feed_visibility_service import (
    UnifiedDocumentFeedVisibilityService,
)
from user.tests.helpers import create_hub_editor, create_random_default_user


class UnifiedDocumentFeedVisibilityServiceTests(TestCase):
    def setUp(self):
        self.activity_feed_cache_warmer = Mock()
        self.service = UnifiedDocumentFeedVisibilityService(
            activity_feed_cache_warmer=self.activity_feed_cache_warmer
        )
        self.moderator = create_random_default_user("feed-vis-mod", moderator=True)
        self.author = create_random_default_user("feed-vis-author")
        self.post = create_post(created_by=self.author, title="Visible post")
        self.unified_document = self.post.unified_document

    def test_moderator_can_exclude_document_from_feed(self):
        # Act
        result = self.service.exclude_from_feed(
            self.unified_document.id, self.moderator
        )

        # Assert
        self.unified_document.document_filter.refresh_from_db()
        self.assertTrue(result.document_filter.is_excluded_in_feed)
        self.assertTrue(self.unified_document.document_filter.is_excluded_in_feed)
        self.activity_feed_cache_warmer.assert_called_once()

    def test_moderator_can_include_document_in_feed(self):
        # Arrange
        self.service.exclude_from_feed(self.unified_document.id, self.moderator)
        self.activity_feed_cache_warmer.reset_mock()

        # Act
        result = self.service.include_in_feed(self.unified_document.id, self.moderator)

        # Assert
        self.assertFalse(result.document_filter.is_excluded_in_feed)
        self.activity_feed_cache_warmer.assert_called_once()

    def test_exclude_and_include_are_idempotent(self):
        # Act
        first = self.service.exclude_from_feed(self.unified_document.id, self.moderator)
        second = self.service.exclude_from_feed(
            self.unified_document.id, self.moderator
        )
        included_once = self.service.include_in_feed(
            self.unified_document.id, self.moderator
        )
        included_twice = self.service.include_in_feed(
            self.unified_document.id, self.moderator
        )

        # Assert
        self.assertTrue(first.document_filter.is_excluded_in_feed)
        self.assertTrue(second.document_filter.is_excluded_in_feed)
        self.assertFalse(included_once.document_filter.is_excluded_in_feed)
        self.assertFalse(included_twice.document_filter.is_excluded_in_feed)
        self.assertEqual(self.activity_feed_cache_warmer.call_count, 2)

    def test_non_moderator_cannot_toggle_visibility(self):
        # Arrange
        editor, _ = create_hub_editor("feed-vis-editor", "feed-vis-hub")

        # Act / Assert
        with self.assertRaises(PermissionError):
            self.service.exclude_from_feed(self.unified_document.id, self.author)
        with self.assertRaises(PermissionError):
            self.service.include_in_feed(self.unified_document.id, editor)

        self.unified_document.document_filter.refresh_from_db()
        self.assertFalse(self.unified_document.document_filter.is_excluded_in_feed)
        self.activity_feed_cache_warmer.assert_not_called()

    def test_missing_document_raises_does_not_exist(self):
        # Act / Assert
        with self.assertRaises(ResearchhubUnifiedDocument.DoesNotExist):
            self.service.exclude_from_feed(999999999, self.moderator)
        self.activity_feed_cache_warmer.assert_not_called()

    def test_creates_document_filter_when_missing(self):
        # Arrange: legacy rows can have a null document_filter
        ResearchhubUnifiedDocument.objects.filter(pk=self.unified_document.pk).update(
            document_filter=None
        )
        self.unified_document.refresh_from_db()
        self.assertIsNone(self.unified_document.document_filter_id)

        # Act
        result = self.service.exclude_from_feed(
            self.unified_document.id, self.moderator
        )

        # Assert
        result.refresh_from_db()
        self.assertIsNotNone(result.document_filter_id)
        self.assertTrue(result.document_filter.is_excluded_in_feed)

    def test_hiding_does_not_delete_feed_entries(self):
        # Arrange
        entry = FeedEntry.objects.create(
            action="PUBLISH",
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=self.post.id,
            unified_document=self.unified_document,
            content={},
            metrics={},
        )

        # Act
        self.service.exclude_from_feed(self.unified_document.id, self.moderator)

        # Assert
        self.assertTrue(FeedEntry.objects.filter(pk=entry.pk).exists())

    def test_list_excluded_returns_only_hidden_newest_first(self):
        # Arrange
        visible = create_post(created_by=self.author, title="Still visible")
        older = create_post(created_by=self.author, title="Older hidden")
        newer = create_post(created_by=self.author, title="Newer hidden")
        self.service.exclude_from_feed(older.unified_document.id, self.moderator)
        self.service.exclude_from_feed(newer.unified_document.id, self.moderator)

        # Act
        ids = list(self.service.list_excluded_from_feed().values_list("id", flat=True))

        # Assert
        self.assertEqual(ids, [newer.unified_document.id, older.unified_document.id])
        self.assertNotIn(visible.unified_document.id, ids)
        self.assertNotIn(self.unified_document.id, ids)

    def test_list_excluded_filters_by_title_query(self):
        # Arrange
        matching = create_post(created_by=self.author, title="UniqueAlpha hidden")
        other = create_post(created_by=self.author, title="Beta hidden")
        self.service.exclude_from_feed(matching.unified_document.id, self.moderator)
        self.service.exclude_from_feed(other.unified_document.id, self.moderator)

        # Act
        matching_ids = list(
            self.service.list_excluded_from_feed("uniquealpha").values_list(
                "id", flat=True
            )
        )
        by_id = list(
            self.service.list_excluded_from_feed(
                str(other.unified_document.id)
            ).values_list("id", flat=True)
        )

        # Assert
        self.assertEqual(matching_ids, [matching.unified_document.id])
        self.assertEqual(by_id, [])

    def test_include_in_feed_drops_document_from_excluded_list(self):
        # Arrange
        self.service.exclude_from_feed(self.unified_document.id, self.moderator)
        self.assertIn(
            self.unified_document.id,
            self.service.list_excluded_from_feed().values_list("id", flat=True),
        )

        # Act
        self.service.include_in_feed(self.unified_document.id, self.moderator)

        # Assert
        self.assertNotIn(
            self.unified_document.id,
            self.service.list_excluded_from_feed().values_list("id", flat=True),
        )

    def test_list_excluded_omits_hidden_papers(self):
        # Arrange: hide still works for preprints; the dashboard list does not.
        paper = create_paper(title="Hidden preprint", uploaded_by=self.author)
        grant = create_post(
            created_by=self.author, title="Hidden grant", document_type=GRANT
        )
        self.service.exclude_from_feed(paper.unified_document.id, self.moderator)
        self.service.exclude_from_feed(grant.unified_document.id, self.moderator)

        # Act
        ids = list(self.service.list_excluded_from_feed().values_list("id", flat=True))

        # Assert
        self.assertIn(grant.unified_document.id, ids)
        self.assertNotIn(paper.unified_document.id, ids)
        paper.unified_document.document_filter.refresh_from_db()
        self.assertTrue(paper.unified_document.document_filter.is_excluded_in_feed)
