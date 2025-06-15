from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APITestCase

from researchhub_comment.models import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from review.models import Review
from user.models import Action
from user.tests.helpers import create_random_default_user


class ContributionViewSetTests(APITestCase):
    def setUp(self):
        self.user = create_random_default_user("test_user")
        self.client.force_authenticate(self.user)

    def test_latest_contributions_with_review(self):
        # Create a unified document and post
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION"
        )
        post = ResearchhubPost.objects.create(
            title="Test Post", created_by=self.user, unified_document=unified_doc
        )

        # Create a comment thread
        thread = RhCommentThreadModel.objects.create(
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=post.id,
            created_by=self.user,
        )

        # Create a comment
        comment = RhCommentModel.objects.create(
            created_by=self.user,
            thread=thread,
            comment_content_json={
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "Test comment"}],
                    }
                ],
            },
        )

        # Create a review for the comment
        Review.objects.create(
            created_by=self.user,
            score=4.5,
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=comment.id,
        )

        # Create an action for the comment
        Action.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=comment.id,
            item=comment,
        )

        # Make request to latest_contributions endpoint
        response = self.client.get("/api/contribution/latest_contributions/")

        # Verify response
        self.assertEqual(response.status_code, 200)
        self.assertTrue(len(response.data["results"]) > 0)

        # Find the comment in the results
        comment_result = None
        for result in response.data["results"]:
            if result["content_type"]["name"] == "rhcommentmodel":
                comment_result = result
                break

        self.assertIsNotNone(comment_result)
        self.assertIn("item", comment_result)
        self.assertIn("review", comment_result["item"])

        # Verify review score is included
        review_data = comment_result["item"]["review"]
        self.assertIsNotNone(review_data)
        self.assertEqual(review_data["score"], 4.5)
