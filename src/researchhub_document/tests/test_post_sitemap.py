from unittest.mock import patch

from rest_framework.test import APITestCase

from purchase.models import Grant
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from user.tests.helpers import create_random_default_user

SITEMAP_URL = "/api/researchhubpost/sitemap/"


class PostSitemapTests(APITestCase):
    def setUp(self):
        self.user = create_random_default_user("sitemap_author")

    def test_lists_public_posts_of_the_requested_type(self):
        # Arrange
        first = create_post(created_by=self.user, document_type=PREREGISTRATION)
        second = create_post(created_by=self.user, document_type=PREREGISTRATION)
        create_post(created_by=self.user, document_type=GRANT)
        removed = create_post(created_by=self.user, document_type=PREREGISTRATION)
        ResearchhubUnifiedDocument.objects.filter(
            id=removed.unified_document_id
        ).update(is_removed=True)
        private = create_post(created_by=self.user, document_type=PREREGISTRATION)
        ResearchhubUnifiedDocument.objects.filter(
            id=private.unified_document_id
        ).update(is_public=False)
        pending = create_post(created_by=self.user, document_type=PREREGISTRATION)
        ResearchhubUnifiedDocument.objects.filter(
            id=pending.unified_document_id
        ).update(status=ResearchhubUnifiedDocument.PENDING)

        # Act
        response = self.client.get(SITEMAP_URL, {"document_type": PREREGISTRATION})

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [post["id"] for post in response.data["results"]], [first.id, second.id]
        )

    def test_returns_only_url_fields(self):
        # Arrange
        post = create_post(created_by=self.user, document_type=PREREGISTRATION)

        # Act
        response = self.client.get(SITEMAP_URL, {"document_type": PREREGISTRATION})

        # Assert
        self.assertEqual(
            set(response.data["results"][0]), {"id", "slug", "updated_date"}
        )
        self.assertEqual(response.data["results"][0]["slug"], post.slug)

    def test_does_not_read_post_bodies(self):
        # Arrange
        create_post(created_by=self.user, document_type=PREREGISTRATION)

        # Act
        with patch.object(ResearchhubPost, "get_full_markdown") as get_full_markdown:
            response = self.client.get(SITEMAP_URL, {"document_type": PREREGISTRATION})

        # Assert
        self.assertEqual(response.status_code, 200)
        get_full_markdown.assert_not_called()

    def test_excludes_grants_pending_moderation(self):
        # Arrange
        open_post = create_post(created_by=self.user, document_type=GRANT)
        Grant.objects.create(
            created_by=self.user,
            unified_document=open_post.unified_document,
            amount=1000,
            status=Grant.OPEN,
        )
        pending_post = create_post(created_by=self.user, document_type=GRANT)
        Grant.objects.create(
            created_by=self.user,
            unified_document=pending_post.unified_document,
            amount=1000,
            status=Grant.PENDING,
        )

        # Act
        response = self.client.get(SITEMAP_URL, {"document_type": GRANT})

        # Assert
        self.assertEqual(
            [post["id"] for post in response.data["results"]], [open_post.id]
        )

    def test_paginates_with_page_size(self):
        # Arrange
        for _ in range(3):
            create_post(created_by=self.user, document_type=PREREGISTRATION)

        # Act
        response = self.client.get(
            SITEMAP_URL, {"document_type": PREREGISTRATION, "page_size": 2}
        )

        # Assert
        self.assertEqual(response.data["count"], 3)
        self.assertEqual(len(response.data["results"]), 2)
        self.assertIsNotNone(response.data["next"])

    def test_rejects_missing_or_unknown_document_type(self):
        # Arrange
        queries = [{}, {"document_type": "PAPER"}]

        for query in queries:
            with self.subTest(query=query):
                # Act
                response = self.client.get(SITEMAP_URL, query)

                # Assert
                self.assertEqual(response.status_code, 400)
