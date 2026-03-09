import uuid

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from feed.models import FeedEntry
from purchase.related_models.grant_application_model import GrantApplication
from purchase.related_models.grant_model import Grant
from researchhub_comment.constants.rh_comment_thread_types import (
    GENERIC_COMMENT,
    PEER_REVIEW,
)
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from utils.test_helpers import AWSMockTestCase

User = get_user_model()
ACTIVITY_LIST_URL = reverse("activity_feed-list")


def _make_user(username=None):
    return User.objects.create_user(
        username=username or uuid.uuid4().hex,
        password=uuid.uuid4().hex,
    )


def _make_feed_entry(
    content_type_model,
    object_id,
    unified_document,
    user=None,
    action_date=None,
):
    ct = ContentType.objects.get_for_model(content_type_model)
    return FeedEntry.objects.create(
        content_type=ct,
        object_id=object_id,
        unified_document=unified_document,
        user=user,
        action="PUBLISH",
        action_date=action_date or timezone.now(),
        content={},
        metrics={},
    )


class ActivityFeedBaseTests(AWSMockTestCase):
    """Shared setUp for activity feed tests."""

    def setUp(self):
        super().setUp()
        self.user = _make_user("activity_user")
        self.client = APIClient()

        self.prereg_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION,
        )
        self.prereg_post = ResearchhubPost.objects.create(
            title="Prereg Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=self.prereg_doc,
        )

        self.grant_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=GRANT,
        )
        self.grant_post = ResearchhubPost.objects.create(
            title="Grant Post",
            created_by=self.user,
            document_type=GRANT,
            unified_document=self.grant_doc,
        )

        self.discussion_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION",
        )
        self.discussion_post = ResearchhubPost.objects.create(
            title="Discussion Post",
            created_by=self.user,
            document_type="DISCUSSION",
            unified_document=self.discussion_doc,
        )

        self.prereg_entry = _make_feed_entry(
            ResearchhubPost,
            self.prereg_post.id,
            self.prereg_doc,
            user=self.user,
        )
        self.grant_entry = _make_feed_entry(
            ResearchhubPost,
            self.grant_post.id,
            self.grant_doc,
            user=self.user,
        )
        self.discussion_entry = _make_feed_entry(
            ResearchhubPost,
            self.discussion_post.id,
            self.discussion_doc,
            user=self.user,
        )


class ActivityFeedListTests(ActivityFeedBaseTests):
    """Test the base list endpoint returns all content types."""

    def test_returns_all_entries(self):
        resp = self.client.get(ACTIVITY_LIST_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = {e["id"] for e in resp.data["results"]}
        self.assertEqual(
            ids,
            {
                self.prereg_entry.id,
                self.grant_entry.id,
                self.discussion_entry.id,
            },
        )

    def test_readonly(self):
        resp = self.client.post(ACTIVITY_LIST_URL, {})
        self.assertEqual(
            resp.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )


class ActivityFeedDocumentTypeFilterTests(ActivityFeedBaseTests):
    """Test filtering by document_type query param."""

    def test_filter_preregistration(self):
        resp = self.client.get(ACTIVITY_LIST_URL, {"document_type": "PREREGISTRATION"})
        ids = {e["id"] for e in resp.data["results"]}
        self.assertEqual(ids, {self.prereg_entry.id})

    def test_filter_grant(self):
        resp = self.client.get(ACTIVITY_LIST_URL, {"document_type": "GRANT"})
        ids = {e["id"] for e in resp.data["results"]}
        self.assertEqual(ids, {self.grant_entry.id})

    def test_filter_case_insensitive(self):
        resp = self.client.get(ACTIVITY_LIST_URL, {"document_type": "grant"})
        ids = {e["id"] for e in resp.data["results"]}
        self.assertEqual(ids, {self.grant_entry.id})

    def test_no_filter_returns_all(self):
        resp = self.client.get(ACTIVITY_LIST_URL)
        self.assertEqual(len(resp.data["results"]), 3)


class ActivityFeedOrderingTests(ActivityFeedBaseTests):
    """Test that results are ordered by action_date descending."""

    def test_ordered_by_action_date_desc(self):
        now = timezone.now()
        old = _make_feed_entry(
            ResearchhubPost,
            self.prereg_post.id,
            self.prereg_doc,
            action_date=now - timezone.timedelta(days=10),
        )
        new = _make_feed_entry(
            ResearchhubPost,
            self.grant_post.id,
            self.grant_doc,
            action_date=now + timezone.timedelta(seconds=5),
        )

        resp = self.client.get(ACTIVITY_LIST_URL)
        ids = [e["id"] for e in resp.data["results"]]
        self.assertLess(ids.index(new.id), ids.index(old.id))


class ActivityFeedGrantFilterTests(AWSMockTestCase):
    """Test ?grant_id= filtering across grant + preregistration documents."""

    def setUp(self):
        super().setUp()
        self.user = _make_user()
        self.client = APIClient()

        # Grant document + post + Grant object
        self.grant_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=GRANT,
        )
        self.grant_post = ResearchhubPost.objects.create(
            title="My Grant",
            created_by=self.user,
            document_type=GRANT,
            unified_document=self.grant_doc,
        )
        self.grant = Grant.objects.create(
            created_by=self.user,
            unified_document=self.grant_doc,
            amount=5000,
            currency="USD",
            status=Grant.OPEN,
        )

        # Preregistration that applied to this grant
        self.prereg_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION,
        )
        self.prereg_post = ResearchhubPost.objects.create(
            title="Applied Prereg",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=self.prereg_doc,
        )
        GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.prereg_post,
            applicant=self.user,
        )

        # Unrelated preregistration (NOT applied to grant)
        self.unrelated_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION,
        )
        self.unrelated_post = ResearchhubPost.objects.create(
            title="Unrelated Prereg",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=self.unrelated_doc,
        )

        # Feed entries: grant post, applied prereg post, unrelated post
        self.grant_entry = _make_feed_entry(
            ResearchhubPost,
            self.grant_post.id,
            self.grant_doc,
            user=self.user,
        )
        self.prereg_entry = _make_feed_entry(
            ResearchhubPost,
            self.prereg_post.id,
            self.prereg_doc,
            user=self.user,
        )
        self.unrelated_entry = _make_feed_entry(
            ResearchhubPost,
            self.unrelated_post.id,
            self.unrelated_doc,
            user=self.user,
        )

    def test_grant_filter_includes_grant_and_applied_prereg(self):
        resp = self.client.get(ACTIVITY_LIST_URL, {"grant_id": self.grant.id})
        ids = {e["id"] for e in resp.data["results"]}
        self.assertIn(self.grant_entry.id, ids)
        self.assertIn(self.prereg_entry.id, ids)
        self.assertNotIn(self.unrelated_entry.id, ids)

    def test_grant_filter_includes_comment_on_prereg(self):
        """Peer-review comment on a preregistration applied to
        this grant must appear in grant-filtered activity."""
        comment_entry = _make_feed_entry(
            RhCommentModel,
            object_id=9999,
            unified_document=self.prereg_doc,
            user=self.user,
        )
        resp = self.client.get(ACTIVITY_LIST_URL, {"grant_id": self.grant.id})
        ids = {e["id"] for e in resp.data["results"]}
        self.assertIn(comment_entry.id, ids)

    def test_grant_filter_includes_comment_on_grant(self):
        """Comment on the grant document itself must appear."""
        comment_entry = _make_feed_entry(
            RhCommentModel,
            object_id=8888,
            unified_document=self.grant_doc,
            user=self.user,
        )
        resp = self.client.get(ACTIVITY_LIST_URL, {"grant_id": self.grant.id})
        ids = {e["id"] for e in resp.data["results"]}
        self.assertIn(comment_entry.id, ids)

    def test_grant_filter_nonexistent_grant(self):
        resp = self.client.get(ACTIVITY_LIST_URL, {"grant_id": 99999})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["results"]), 0)

    def test_grant_with_no_applications(self):
        """Grant with no applications still shows the grant's own activity."""
        empty_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=GRANT,
        )
        empty_post = ResearchhubPost.objects.create(
            title="Empty Grant Post",
            created_by=self.user,
            document_type=GRANT,
            unified_document=empty_doc,
        )
        empty_grant = Grant.objects.create(
            created_by=self.user,
            unified_document=empty_doc,
            amount=100,
            currency="USD",
            status=Grant.OPEN,
        )
        grant_entry = _make_feed_entry(
            ResearchhubPost,
            empty_post.id,
            empty_doc,
            user=self.user,
        )
        resp = self.client.get(ACTIVITY_LIST_URL, {"grant_id": empty_grant.id})
        ids = {e["id"] for e in resp.data["results"]}
        self.assertEqual(ids, {grant_entry.id})


class ActivityFeedContentTypeFilterTests(ActivityFeedBaseTests):
    """Test ?content_type= filtering."""

    def setUp(self):
        super().setUp()
        self.comment_entry = _make_feed_entry(
            RhCommentModel,
            object_id=7777,
            unified_document=self.prereg_doc,
            user=self.user,
        )

    def test_filter_comments_only(self):
        resp = self.client.get(
            ACTIVITY_LIST_URL,
            {"content_type": "RHCOMMENTMODEL"},
        )
        ids = {e["id"] for e in resp.data["results"]}
        self.assertEqual(ids, {self.comment_entry.id})

    def test_filter_posts_only(self):
        resp = self.client.get(
            ACTIVITY_LIST_URL,
            {"content_type": "RESEARCHHUBPOST"},
        )
        ids = {e["id"] for e in resp.data["results"]}
        self.assertTrue(all(e.id not in ids for e in [self.comment_entry]))
        self.assertIn(self.prereg_entry.id, ids)

    def test_filter_case_insensitive(self):
        resp = self.client.get(
            ACTIVITY_LIST_URL,
            {"content_type": "rhcommentmodel"},
        )
        ids = {e["id"] for e in resp.data["results"]}
        self.assertEqual(ids, {self.comment_entry.id})

    def test_invalid_content_type_returns_empty(self):
        resp = self.client.get(
            ACTIVITY_LIST_URL,
            {"content_type": "NONEXISTENT"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["results"]), 0)

    def test_combined_grant_and_content_type(self):
        """grant_id + content_type should intersect both filters."""
        grant_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=GRANT,
        )
        grant_post = ResearchhubPost.objects.create(
            title="CT Grant",
            created_by=self.user,
            document_type=GRANT,
            unified_document=grant_doc,
        )
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=grant_doc,
            amount=1000,
            currency="USD",
            status=Grant.OPEN,
        )
        post_entry = _make_feed_entry(
            ResearchhubPost,
            grant_post.id,
            grant_doc,
            user=self.user,
        )
        comment_entry = _make_feed_entry(
            RhCommentModel,
            object_id=6666,
            unified_document=grant_doc,
            user=self.user,
        )

        resp = self.client.get(
            ACTIVITY_LIST_URL,
            {
                "grant_id": grant.id,
                "content_type": "RHCOMMENTMODEL",
            },
        )
        ids = {e["id"] for e in resp.data["results"]}
        self.assertIn(comment_entry.id, ids)
        self.assertNotIn(post_entry.id, ids)


class ActivityFeedScopeGrantsTests(AWSMockTestCase):
    """Test ?scope=grants returns all grant-related activity."""

    def setUp(self):
        super().setUp()
        self.user = _make_user()
        self.client = APIClient()

        # Grant A with an applied preregistration
        self.grant_a_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=GRANT,
        )
        self.grant_a_post = ResearchhubPost.objects.create(
            title="Grant A",
            created_by=self.user,
            document_type=GRANT,
            unified_document=self.grant_a_doc,
        )
        self.grant_a = Grant.objects.create(
            created_by=self.user,
            unified_document=self.grant_a_doc,
            amount=1000,
            currency="USD",
            status=Grant.OPEN,
        )
        self.prereg_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION,
        )
        self.prereg_post = ResearchhubPost.objects.create(
            title="Prereg for Grant A",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=self.prereg_doc,
        )
        GrantApplication.objects.create(
            grant=self.grant_a,
            preregistration_post=self.prereg_post,
            applicant=self.user,
        )

        # Grant B with no applications
        self.grant_b_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=GRANT,
        )
        self.grant_b_post = ResearchhubPost.objects.create(
            title="Grant B",
            created_by=self.user,
            document_type=GRANT,
            unified_document=self.grant_b_doc,
        )
        Grant.objects.create(
            created_by=self.user,
            unified_document=self.grant_b_doc,
            amount=2000,
            currency="USD",
            status=Grant.OPEN,
        )

        # Unrelated discussion (should be excluded)
        self.disc_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION",
        )
        self.disc_post = ResearchhubPost.objects.create(
            title="Discussion",
            created_by=self.user,
            document_type="DISCUSSION",
            unified_document=self.disc_doc,
        )

        # Unrelated prereg NOT applied to any grant
        self.lone_prereg_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION,
        )
        self.lone_prereg_post = ResearchhubPost.objects.create(
            title="Lone Prereg",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=self.lone_prereg_doc,
        )

        # Feed entries
        self.grant_a_entry = _make_feed_entry(
            ResearchhubPost,
            self.grant_a_post.id,
            self.grant_a_doc,
            user=self.user,
        )
        self.prereg_entry = _make_feed_entry(
            ResearchhubPost,
            self.prereg_post.id,
            self.prereg_doc,
            user=self.user,
        )
        self.grant_b_entry = _make_feed_entry(
            ResearchhubPost,
            self.grant_b_post.id,
            self.grant_b_doc,
            user=self.user,
        )
        self.disc_entry = _make_feed_entry(
            ResearchhubPost,
            self.disc_post.id,
            self.disc_doc,
            user=self.user,
        )
        self.lone_prereg_entry = _make_feed_entry(
            ResearchhubPost,
            self.lone_prereg_post.id,
            self.lone_prereg_doc,
            user=self.user,
        )

    def test_scope_grants_includes_all_grants_and_applied_preregs(
        self,
    ):
        resp = self.client.get(ACTIVITY_LIST_URL, {"scope": "grants"})
        ids = {e["id"] for e in resp.data["results"]}
        self.assertIn(self.grant_a_entry.id, ids)
        self.assertIn(self.grant_b_entry.id, ids)
        self.assertIn(self.prereg_entry.id, ids)

    def test_scope_grants_excludes_unrelated(self):
        resp = self.client.get(ACTIVITY_LIST_URL, {"scope": "grants"})
        ids = {e["id"] for e in resp.data["results"]}
        self.assertNotIn(self.disc_entry.id, ids)
        self.assertNotIn(self.lone_prereg_entry.id, ids)

    def test_scope_grants_includes_comments(self):
        """Comments on any grant-related doc should appear."""
        comment_on_grant = _make_feed_entry(
            RhCommentModel,
            object_id=5555,
            unified_document=self.grant_a_doc,
            user=self.user,
        )
        comment_on_prereg = _make_feed_entry(
            RhCommentModel,
            object_id=4444,
            unified_document=self.prereg_doc,
            user=self.user,
        )
        resp = self.client.get(ACTIVITY_LIST_URL, {"scope": "grants"})
        ids = {e["id"] for e in resp.data["results"]}
        self.assertIn(comment_on_grant.id, ids)
        self.assertIn(comment_on_prereg.id, ids)

    def test_scope_grants_combined_with_content_type(self):
        """scope=grants + content_type should intersect."""
        comment_entry = _make_feed_entry(
            RhCommentModel,
            object_id=3333,
            unified_document=self.grant_b_doc,
            user=self.user,
        )
        resp = self.client.get(
            ACTIVITY_LIST_URL,
            {"scope": "grants", "content_type": "RHCOMMENTMODEL"},
        )
        ids = {e["id"] for e in resp.data["results"]}
        self.assertIn(comment_entry.id, ids)
        self.assertNotIn(self.grant_a_entry.id, ids)
        self.assertNotIn(self.grant_b_entry.id, ids)

    def test_scope_case_insensitive(self):
        resp = self.client.get(ACTIVITY_LIST_URL, {"scope": "GRANTS"})
        ids = {e["id"] for e in resp.data["results"]}
        self.assertIn(self.grant_a_entry.id, ids)


class ActivityFeedActionDateOrderingTests(AWSMockTestCase):
    """Verify sorting uses action_date, not created_date."""

    def setUp(self):
        super().setUp()
        self.user = _make_user()
        self.client = APIClient()

    def test_action_date_determines_order_not_created_date(self):
        """An entry created later but with an older action_date
        should appear after an entry with a newer action_date."""
        now = timezone.now()

        doc_a = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION,
        )
        post_a = ResearchhubPost.objects.create(
            title="Post A",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=doc_a,
        )

        doc_b = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION,
        )
        post_b = ResearchhubPost.objects.create(
            title="Post B",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=doc_b,
        )

        # entry_old: created_date is "now" but action_date is old
        entry_old = _make_feed_entry(
            ResearchhubPost,
            post_a.id,
            doc_a,
            user=self.user,
            action_date=now - timezone.timedelta(days=30),
        )

        # entry_new: created_date is also "now" but action_date
        # is recent
        entry_new = _make_feed_entry(
            ResearchhubPost,
            post_b.id,
            doc_b,
            user=self.user,
            action_date=now - timezone.timedelta(minutes=5),
        )

        resp = self.client.get(ACTIVITY_LIST_URL)
        ids = [e["id"] for e in resp.data["results"]]
        self.assertLess(
            ids.index(entry_new.id),
            ids.index(entry_old.id),
        )


@override_settings(CELERY_TASK_ALWAYS_EAGER=False)
class ActivityFeedPeerReviewFilterTests(AWSMockTestCase):
    """
    Test that `peer_reviews` scope returns all feed entries for documents
    that have peer review comments.
    """

    def setUp(self):
        super().setUp()
        self.user = _make_user()
        self.client = APIClient()

        self.doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION,
        )
        self.post = ResearchhubPost.objects.create(
            title="Test Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=self.doc,
        )

        post_ct = ContentType.objects.get_for_model(ResearchhubPost)
        thread = RhCommentThreadModel.objects.create(
            thread_type=PEER_REVIEW,
            content_type=post_ct,
            object_id=self.post.id,
            created_by=self.user,
        )

        self.peer_review_comment = RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "peer review"}]},
            comment_type=PEER_REVIEW,
            created_by=self.user,
            thread=thread,
        )
        self.generic_comment = RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "generic comment"}]},
            comment_type=GENERIC_COMMENT,
            created_by=self.user,
            thread=thread,
        )

        # Manually create feed entries (bypassing signals)
        comment_ct = ContentType.objects.get_for_model(RhCommentModel)
        self.peer_review_entry = FeedEntry.objects.create(
            content_type=comment_ct,
            object_id=self.peer_review_comment.id,
            unified_document=self.doc,
            user=self.user,
            action="PUBLISH",
            action_date=timezone.now(),
            content={},
            metrics={},
        )
        self.generic_comment_entry = FeedEntry.objects.create(
            content_type=comment_ct,
            object_id=self.generic_comment.id,
            unified_document=self.doc,
            user=self.user,
            action="PUBLISH",
            action_date=timezone.now(),
            content={},
            metrics={},
        )
        self.post_entry = _make_feed_entry(
            ResearchhubPost,
            self.post.id,
            self.doc,
            user=self.user,
        )

        # Unrelated document with NO peer reviews (should be excluded)
        self.unrelated_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION",
        )
        self.unrelated_post = ResearchhubPost.objects.create(
            title="Unrelated Post",
            created_by=self.user,
            document_type="DISCUSSION",
            unified_document=self.unrelated_doc,
        )
        self.unrelated_entry = _make_feed_entry(
            ResearchhubPost,
            self.unrelated_post.id,
            self.unrelated_doc,
            user=self.user,
        )

    def test_scope_peer_reviews_includes_document_and_review_entries(self):
        """
        Document entries and peer review comment entries should be included,
        but generic comments should be excluded.
        """
        # Act
        resp = self.client.get(ACTIVITY_LIST_URL, {"scope": "peer_reviews"})

        # Assert
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = {e["id"] for e in resp.data["results"]}
        self.assertIn(self.peer_review_entry.id, ids)
        self.assertIn(self.post_entry.id, ids)
        self.assertNotIn(self.generic_comment_entry.id, ids)

    def test_scope_peer_reviews_excludes_unrelated_documents(self):
        """
        Documents without peer reviews should not appear.
        """
        # Act
        resp = self.client.get(ACTIVITY_LIST_URL, {"scope": "peer_reviews"})

        # Assert
        ids = {e["id"] for e in resp.data["results"]}
        self.assertNotIn(self.unrelated_entry.id, ids)

    def test_scope_peer_reviews_empty_when_none_exist(self):
        # Arrange
        FeedEntry.objects.all().delete()

        # Act
        resp = self.client.get(ACTIVITY_LIST_URL, {"scope": "peer_reviews"})

        # Assert
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["results"]), 0)
