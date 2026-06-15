from decimal import Decimal
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from feed.models import FeedEntry
from purchase.related_models.grant_model import Grant
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    GRANT,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from search.documents.post import PostDocument
from user.tests.helpers import create_random_authenticated_user


def create_feed_entry_for_post(post, hot_score_v2=0):
    post_content_type = ContentType.objects.get_for_model(ResearchhubPost)
    return FeedEntry.objects.create(
        content_type=post_content_type,
        object_id=post.id,
        action=FeedEntry.PUBLISH,
        action_date=timezone.now(),
        hot_score_v2=hot_score_v2,
        unified_document=post.unified_document,
    )


class PostDocumentTests(TestCase):
    def setUp(self):
        self.document = PostDocument()
        self.user = create_random_authenticated_user("testuser")

    def _create_post(self, title="Test Post"):
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=DISCUSSION,
        )
        return ResearchhubPost.objects.create(
            created_by=self.user,
            title=title,
            renderable_text="Test content",
            document_type=DISCUSSION,
            unified_document=unified_doc,
        )

    def test_prepare_hot_score_v2_with_feed_entry(self):
        post = self._create_post("Hot Post")
        create_feed_entry_for_post(post, hot_score_v2=200)

        result = self.document.prepare_hot_score_v2(post)

        self.assertEqual(result, 200)

    def test_prepare_hot_score_v2_without_feed_entry(self):
        post = self._create_post("Cold Post")

        result = self.document.prepare_hot_score_v2(post)

        self.assertEqual(result, 0)

    def test_prepare_hot_score_v2_returns_zero_on_exception(self):
        post = self._create_post("Error Post")

        with patch(
            "search.documents.post.ContentType.objects.get_for_model",
            side_effect=Exception("DB error"),
        ):
            result = self.document.prepare_hot_score_v2(post)

        self.assertEqual(result, 0)

    def test_should_index_object_excludes_private_unified_document(self):
        post = self._create_post("Private Post")
        post.unified_document.is_public = False

        self.assertFalse(self.document.should_index_object(post))

    def test_should_index_object_includes_public_unremoved_post(self):
        post = self._create_post("Public Post")

        self.assertTrue(self.document.should_index_object(post))

    def test_should_index_object_excludes_pending_post(self):
        post = self._create_post("Pending Post")
        post.unified_document.status = ResearchhubUnifiedDocument.PENDING

        self.assertFalse(self.document.should_index_object(post))

    def test_should_index_object_excludes_declined_post(self):
        post = self._create_post("Declined Post")
        post.unified_document.status = ResearchhubUnifiedDocument.DECLINED

        self.assertFalse(self.document.should_index_object(post))

    def _create_grant_post(self, status):
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type=GRANT)
        post = ResearchhubPost.objects.create(
            created_by=self.user,
            title="Grant Post",
            renderable_text="Grant content",
            document_type=GRANT,
            unified_document=unified_doc,
        )
        Grant.objects.create(
            created_by=self.user,
            unified_document=unified_doc,
            amount=Decimal("1000.00"),
            currency="USD",
            organization="Org",
            description="desc",
            status=status,
        )
        return post

    def test_should_index_object_excludes_pending_grant(self):
        """Grants gate on Grant.status, not the (always APPROVED) post status."""
        post = self._create_grant_post(Grant.PENDING)

        self.assertFalse(self.document.should_index_object(post))

    def test_should_index_object_includes_open_grant(self):
        post = self._create_grant_post(Grant.OPEN)

        self.assertTrue(self.document.should_index_object(post))
