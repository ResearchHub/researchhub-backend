from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from feed.models import FeedEntry
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from search.documents.post import PostDocument
from user.tests.helpers import create_random_authenticated_user


class PostDocumentTests(TestCase):
    def setUp(self):
        self.document = PostDocument()
        self.user = create_random_authenticated_user("testuser")

    def _create_post(self, title="Test Post"):
        return ResearchhubPost.objects.create(
            created_by=self.user,
            title=title,
            renderable_text="Test content",
        )

    def test_prepare_hot_score_v2_with_feed_entry(self):
        post = self._create_post("Hot Post")
        post_content_type = ContentType.objects.get_for_model(ResearchhubPost)
        FeedEntry.objects.create(
            content_type=post_content_type,
            object_id=post.id,
            hot_score_v2=200,
        )

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

