from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
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

# Empirically measured query count for the user-generated feed action with
# 3 fixture entries (paper, post, comment) and pre-populated `content`.
# Breakdown: 1 main FeedEntry fetch with select_related joins, 1 hubs fetch,
# 3 GenericForeignKey item lookups (existing serializer-level N+1 via
# `external_metadata` / `bounties` SerializerMethodFields - out of scope to
# fix here), and 3 user-vote lookups (one per content type present).
# Bumping this requires a justified change; otherwise it indicates an N+1
# regression on a moderation surface intended for staff use.
EXPECTED_QUERY_COUNT = 8


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

        # User-uploaded paper. Flagged copyright-restricted to confirm the
        # action bypasses the main feed's pdf_copyright filter.
        cls.user_paper = create_paper(
            title="User Uploaded Paper", uploaded_by=cls.uploader
        )
        cls.user_paper_entry = FeedEntry.objects.create(
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

        # System-imported paper (user=None) - must NOT appear in results.
        cls.system_paper = create_paper(title="System Imported Paper")
        cls.system_paper_entry = FeedEntry.objects.create(
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
        cls.user_post_entry = FeedEntry.objects.create(
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
        cls.user_comment_entry = FeedEntry.objects.create(
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

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _user_generated_url(self):
        return reverse("feed-user-generated")

    def _ids_for(self, response, content_type):
        """Extract content_object ids from a feed response, filtered by type."""
        type_str = content_type.model.upper()
        return [
            r["content_object"]["id"]
            for r in response.data["results"]
            if r["content_type"] == type_str
        ]

    def test_anonymous_user_denied(self):
        response = self.client.get(self._user_generated_url())

        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_non_moderator_forbidden(self):
        self.client.force_authenticate(self.regular_user)

        response = self.client.get(self._user_generated_url())

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_moderator_receives_paginated_results(self):
        self.client.force_authenticate(self.moderator_user)

        response = self.client.get(self._user_generated_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data)
        self.assertIn("next", response.data)

    def test_excludes_entries_without_user(self):
        """Entries with `user=None` (auto-imports) must not appear."""
        self.client.force_authenticate(self.moderator_user)

        response = self.client.get(self._user_generated_url())

        self.assertNotIn(
            self.system_paper.id,
            self._ids_for(response, self.paper_content_type),
        )

    def test_bypasses_main_feed_filters(self):
        """
        Moderator feed must show entries the main feed hides via
        `FeedFilteringBackend`: papers outside the preprint-hub allowlist
        and entries flagged `pdf_copyright_allows_display=False`. Both apply
        to `user_paper_entry`.
        """
        self.client.force_authenticate(self.moderator_user)

        response = self.client.get(self._user_generated_url())

        self.assertIn(
            self.user_paper.id, self._ids_for(response, self.paper_content_type)
        )

    def test_includes_comments(self):
        """Per chosen scope, comment entries with a user are included."""
        self.client.force_authenticate(self.moderator_user)

        response = self.client.get(self._user_generated_url())

        self.assertIn(
            self.user_comment.id,
            self._ids_for(response, self.comment_content_type),
        )

    def test_results_ordered_by_action_date_desc(self):
        self.client.force_authenticate(self.moderator_user)

        response = self.client.get(self._user_generated_url())

        results = response.data["results"]
        self.assertGreaterEqual(len(results), 2)

        action_dates = [r["action_date"] for r in results]
        self.assertEqual(action_dates, sorted(action_dates, reverse=True))

    def test_response_includes_feed_source_header(self):
        self.client.force_authenticate(self.moderator_user)

        response = self.client.get(self._user_generated_url())

        self.assertEqual(response["RH-Feed-Source"], "rh-user-generated")

    def test_pagination_next_link_when_exceeding_page_size(self):
        """
        Verify FeedPagination splits results across pages when total entries
        exceed `page_size`. Note: FeedPagination currently emits `next` on
        every non-empty page (see the FIXME in
        `feed.views.common.FeedPagination.get_paginated_response`), so we
        only assert presence on page 1 and that page 2 returns the remaining
        non-overlapping entries.
        """
        self.client.force_authenticate(self.moderator_user)

        page_one = self.client.get(self._user_generated_url(), {"page_size": 2})
        self.assertEqual(page_one.status_code, status.HTTP_200_OK)
        self.assertEqual(len(page_one.data["results"]), 2)
        self.assertIsNotNone(page_one.data["next"])

        page_two = self.client.get(
            self._user_generated_url(), {"page_size": 2, "page": 2}
        )
        self.assertEqual(page_two.status_code, status.HTTP_200_OK)
        # 3 user-generated entries (paper, post, comment) -> 1 left on page 2.
        self.assertEqual(len(page_two.data["results"]), 1)

        page_one_ids = {r["id"] for r in page_one.data["results"]}
        page_two_ids = {r["id"] for r in page_two.data["results"]}
        self.assertTrue(page_one_ids.isdisjoint(page_two_ids))

    def test_query_count_is_bounded(self):
        """
        Lock the per-request query count to guard against N+1 regressions.

        Pre-populates `FeedEntry.content` so the serializer takes the cached
        JSON path (the production path) instead of `serialize_feed_item`,
        which itself fans out queries. Re-fetches entries from DB so we
        don't mutate the class-level fixtures from `setUpTestData`.
        """
        for entry in FeedEntry.objects.filter(user__isnull=False):
            entry.content = {
                "id": entry.object_id,
                "content_type": entry.content_type.model.upper(),
            }
            entry.save(update_fields=["content"])

        self.client.force_authenticate(self.moderator_user)

        with self.assertNumQueries(EXPECTED_QUERY_COUNT):
            response = self.client.get(self._user_generated_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
