from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from feed.models import FeedEntry
from paper.models import Paper
from paper.tests.helpers import create_paper
from researchhub_comment.models import RhCommentModel
from researchhub_comment.tests.helpers import create_rh_comment
from researchhub_document.helpers import create_post
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.tests.helpers import create_random_default_user


class UserGeneratedFeedViewTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.uploader = create_random_default_user("uploader")
        cls.commenter = create_random_default_user("commenter")
        cls.regular_user = create_random_default_user("regular")
        cls.moderator_user = create_random_default_user("mod_user", moderator=True)

        cls.paper_content_type = ContentType.objects.get_for_model(Paper)
        cls.post_content_type = ContentType.objects.get_for_model(ResearchhubPost)
        cls.comment_content_type = ContentType.objects.get_for_model(RhCommentModel)

        now = timezone.now()

        cls.user_paper = create_paper(
            title="User Uploaded Paper", uploaded_by=cls.uploader
        )
        FeedEntry.objects.create(
            action="PUBLISH",
            action_date=now,
            content_type=cls.paper_content_type,
            object_id=cls.user_paper.id,
            unified_document=cls.user_paper.unified_document,
            user=cls.uploader,
            content={},
            metrics={},
            pdf_copyright_allows_display=False,
        )

        cls.system_paper = create_paper(title="System Imported Paper")
        FeedEntry.objects.create(
            action="PUBLISH",
            action_date=now - timedelta(days=1),
            content_type=cls.paper_content_type,
            object_id=cls.system_paper.id,
            unified_document=cls.system_paper.unified_document,
            user=None,
            content={},
            metrics={},
            pdf_copyright_allows_display=True,
        )

        cls.user_post = create_post(
            title="User Discussion Post", created_by=cls.uploader
        )
        FeedEntry.objects.create(
            action="PUBLISH",
            action_date=now - timedelta(hours=1),
            content_type=cls.post_content_type,
            object_id=cls.user_post.id,
            unified_document=cls.user_post.unified_document,
            user=cls.uploader,
            content={},
            metrics={},
            pdf_copyright_allows_display=True,
        )

        cls.user_comment = create_rh_comment(
            post=cls.user_post, created_by=cls.commenter
        )
        FeedEntry.objects.create(
            action="PUBLISH",
            action_date=now - timedelta(hours=2),
            content_type=cls.comment_content_type,
            object_id=cls.user_comment.id,
            unified_document=cls.user_post.unified_document,
            user=cls.commenter,
            content={},
            metrics={},
            pdf_copyright_allows_display=True,
        )

    def _user_generated_url(self):
        return reverse("feed-user-generated")

    def _ids_for(self, response, content_type):
        type_str = content_type.model.upper()
        return [
            r["content_object"]["id"]
            for r in response.data["results"]
            if r["content_type"] == type_str
        ]

    def test_non_moderator_forbidden(self):
        self.client.force_authenticate(self.regular_user)

        response = self.client.get(self._user_generated_url())

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_returns_user_generated_papers_posts_and_comments(self):
        self.client.force_authenticate(self.moderator_user)

        response = self.client.get(self._user_generated_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["RH-Feed-Source"], "rh-user-generated")
        self.assertIn(
            self.user_paper.id, self._ids_for(response, self.paper_content_type)
        )
        self.assertIn(
            self.user_post.id, self._ids_for(response, self.post_content_type)
        )
        self.assertIn(
            self.user_comment.id,
            self._ids_for(response, self.comment_content_type),
        )

    def test_excludes_entries_without_user(self):
        self.client.force_authenticate(self.moderator_user)

        response = self.client.get(self._user_generated_url())

        self.assertNotIn(
            self.system_paper.id,
            self._ids_for(response, self.paper_content_type),
        )

    def test_results_ordered_by_action_date_desc(self):
        self.client.force_authenticate(self.moderator_user)

        response = self.client.get(self._user_generated_url())

        action_dates = [r["action_date"] for r in response.data["results"]]
        self.assertEqual(action_dates, sorted(action_dates, reverse=True))
