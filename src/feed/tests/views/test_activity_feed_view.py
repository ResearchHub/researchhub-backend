from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from feed.models import FeedEntry
from purchase.models import Fundraise
from purchase.related_models.grant_application_model import GrantApplication
from purchase.related_models.grant_model import Grant
from purchase.related_models.purchase_model import Purchase
from purchase.related_models.usd_fundraise_contribution_model import (
    UsdFundraiseContribution,
)
from researchhub_comment.constants.rh_comment_thread_types import (
    COMMUNITY_REVIEW,
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
from utils.test_helpers import AWSMockTestCase, create_test_user

User = get_user_model()
ACTIVITY_LIST_URL = reverse("activity_feed-list")


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
        self.user = create_test_user("activity_user")
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
        self.user = create_test_user()
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
        self.user = create_test_user()
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
        self.user = create_test_user()
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
        self.user = create_test_user()
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
        self.community_review_comment = RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "community review"}]},
            comment_type=COMMUNITY_REVIEW,
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
        self.community_review_entry = FeedEntry.objects.create(
            content_type=comment_ct,
            object_id=self.community_review_comment.id,
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

    def test_scope_peer_reviews_returns_only_peer_review_entries(self):
        """
        Only feed entries that are peer review comments (PEER_REVIEW or
        COMMUNITY_REVIEW) should be returned.
        """
        # Act
        resp = self.client.get(ACTIVITY_LIST_URL, {"scope": "peer_reviews"})

        # Assert
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = {e["id"] for e in resp.data["results"]}
        self.assertIn(self.peer_review_entry.id, ids)
        self.assertIn(self.community_review_entry.id, ids)
        self.assertNotIn(self.generic_comment_entry.id, ids)
        self.assertNotIn(self.post_entry.id, ids)

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


class ActivityFeedFinancialScopeTests(AWSMockTestCase):
    """
    Test financial scope returns fundraise contribution activities.
    """

    def setUp(self):
        super().setUp()
        self.user = create_test_user()
        self.client = APIClient()

        self.proposal_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION,
        )
        self.proposal_post = ResearchhubPost.objects.create(
            title="Funding Proposal",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=self.proposal_doc,
        )
        self.fundraise = Fundraise.objects.create(
            unified_document=self.proposal_doc,
            created_by=self.user,
            goal_amount=Decimal("1000.00"),
            goal_currency="USD",
            status=Fundraise.OPEN,
        )

        fundraise_ct = ContentType.objects.get_for_model(Fundraise)
        self.rsc_contribution = Purchase.objects.create(
            user=self.user,
            content_type=fundraise_ct,
            object_id=self.fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            purchase_method=Purchase.OFF_CHAIN,
            amount="100",
        )
        self.usd_contribution = UsdFundraiseContribution.objects.create(
            user=self.user,
            fundraise=self.fundraise,
            amount_cents=5500,
            fee_cents=495,
            origin_fund_id="test-origin",
            destination_org_id="test-destination",
        )

        self.rsc_entry = _make_feed_entry(
            Purchase,
            self.rsc_contribution.id,
            self.proposal_doc,
            user=self.user,
        )
        self.usd_entry = _make_feed_entry(
            UsdFundraiseContribution,
            self.usd_contribution.id,
            self.proposal_doc,
            user=self.user,
        )

        self.unrelated_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION",
        )
        self.unrelated_post = ResearchhubPost.objects.create(
            title="Unrelated Discussion",
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

        post_ct = ContentType.objects.get_for_model(ResearchhubPost)
        self.boost_purchase = Purchase.objects.create(
            user=self.user,
            content_type=post_ct,
            object_id=self.unrelated_post.id,
            purchase_type=Purchase.BOOST,
            purchase_method=Purchase.OFF_CHAIN,
            amount="10",
        )
        self.boost_entry = _make_feed_entry(
            Purchase,
            self.boost_purchase.id,
            self.unrelated_doc,
            user=self.user,
        )

    def test_scope_financial_includes_rsc_and_usd_contributions(self):
        # Act
        resp = self.client.get(ACTIVITY_LIST_URL, {"scope": "financial"})

        # Assert
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = {entry["id"] for entry in resp.data["results"]}
        self.assertIn(self.rsc_entry.id, ids)
        self.assertIn(self.usd_entry.id, ids)
        self.assertNotIn(self.unrelated_entry.id, ids)
        self.assertNotIn(self.boost_entry.id, ids)


class ActivityFeedFunderFilterTests(AWSMockTestCase):
    """Test ?funder_id= filtering across grants created by or
    contacted by a funder."""

    def setUp(self):
        super().setUp()
        self.funder = create_test_user("funder", email="funder@example.com")
        self.other_user = create_test_user("other", email="other@example.com")
        self.applicant = create_test_user("applicant", email="applicant@example.com")
        self.client = APIClient()

        # Grant A: created by funder, OPEN, has an applied preregistration
        self.grant_a_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=GRANT,
        )
        self.grant_a_post = ResearchhubPost.objects.create(
            title="Funder Grant A",
            created_by=self.funder,
            document_type=GRANT,
            unified_document=self.grant_a_doc,
        )
        self.grant_a = Grant.objects.create(
            created_by=self.funder,
            unified_document=self.grant_a_doc,
            amount=1000,
            currency="USD",
            status=Grant.OPEN,
        )
        self.applied_prereg_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION,
        )
        self.applied_prereg_post = ResearchhubPost.objects.create(
            title="Applied Prereg",
            created_by=self.applicant,
            document_type=PREREGISTRATION,
            unified_document=self.applied_prereg_doc,
        )
        GrantApplication.objects.create(
            grant=self.grant_a,
            preregistration_post=self.applied_prereg_post,
            applicant=self.applicant,
        )

        # Grant B: created by other_user, funder is a CONTACT, OPEN, no apps
        self.grant_b_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=GRANT,
        )
        self.grant_b_post = ResearchhubPost.objects.create(
            title="Contact Grant B",
            created_by=self.other_user,
            document_type=GRANT,
            unified_document=self.grant_b_doc,
        )
        self.grant_b = Grant.objects.create(
            created_by=self.other_user,
            unified_document=self.grant_b_doc,
            amount=2000,
            currency="USD",
            status=Grant.OPEN,
        )
        self.grant_b.contacts.add(self.funder)

        # Grant C: created by other_user, funder NOT involved (excluded)
        self.grant_c_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=GRANT,
        )
        self.grant_c_post = ResearchhubPost.objects.create(
            title="Unrelated Grant C",
            created_by=self.other_user,
            document_type=GRANT,
            unified_document=self.grant_c_doc,
        )
        Grant.objects.create(
            created_by=self.other_user,
            unified_document=self.grant_c_doc,
            amount=3000,
            currency="USD",
            status=Grant.OPEN,
        )

        # Grant D: created by funder but PENDING (excluded)
        self.grant_d_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=GRANT,
        )
        self.grant_d_post = ResearchhubPost.objects.create(
            title="Pending Funder Grant D",
            created_by=self.funder,
            document_type=GRANT,
            unified_document=self.grant_d_doc,
        )
        Grant.objects.create(
            created_by=self.funder,
            unified_document=self.grant_d_doc,
            amount=4000,
            currency="USD",
            status=Grant.PENDING,
        )

        # Grant E: created by funder and COMPLETED (included)
        self.grant_e_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=GRANT,
        )
        self.grant_e_post = ResearchhubPost.objects.create(
            title="Completed Funder Grant E",
            created_by=self.funder,
            document_type=GRANT,
            unified_document=self.grant_e_doc,
        )
        Grant.objects.create(
            created_by=self.funder,
            unified_document=self.grant_e_doc,
            amount=5000,
            currency="USD",
            status=Grant.COMPLETED,
        )

        # Grant F: created by funder and CLOSED (excluded)
        self.grant_f_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=GRANT,
        )
        self.grant_f_post = ResearchhubPost.objects.create(
            title="Closed Funder Grant F",
            created_by=self.funder,
            document_type=GRANT,
            unified_document=self.grant_f_doc,
        )
        Grant.objects.create(
            created_by=self.funder,
            unified_document=self.grant_f_doc,
            amount=6000,
            currency="USD",
            status=Grant.CLOSED,
        )

        # Lone preregistration NOT applied to any grant (excluded)
        self.lone_prereg_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION,
        )
        self.lone_prereg_post = ResearchhubPost.objects.create(
            title="Lone Prereg",
            created_by=self.applicant,
            document_type=PREREGISTRATION,
            unified_document=self.lone_prereg_doc,
        )

        # Feed entries for each post above
        self.grant_a_entry = _make_feed_entry(
            ResearchhubPost,
            self.grant_a_post.id,
            self.grant_a_doc,
            user=self.funder,
        )
        self.applied_prereg_entry = _make_feed_entry(
            ResearchhubPost,
            self.applied_prereg_post.id,
            self.applied_prereg_doc,
            user=self.applicant,
        )
        self.grant_b_entry = _make_feed_entry(
            ResearchhubPost,
            self.grant_b_post.id,
            self.grant_b_doc,
            user=self.other_user,
        )
        self.grant_c_entry = _make_feed_entry(
            ResearchhubPost,
            self.grant_c_post.id,
            self.grant_c_doc,
            user=self.other_user,
        )
        self.grant_d_entry = _make_feed_entry(
            ResearchhubPost,
            self.grant_d_post.id,
            self.grant_d_doc,
            user=self.funder,
        )
        self.grant_e_entry = _make_feed_entry(
            ResearchhubPost,
            self.grant_e_post.id,
            self.grant_e_doc,
            user=self.funder,
        )
        self.grant_f_entry = _make_feed_entry(
            ResearchhubPost,
            self.grant_f_post.id,
            self.grant_f_doc,
            user=self.funder,
        )
        self.lone_prereg_entry = _make_feed_entry(
            ResearchhubPost,
            self.lone_prereg_post.id,
            self.lone_prereg_doc,
            user=self.applicant,
        )

    def test_funder_filter_includes_grant_created_by_funder(self):
        resp = self.client.get(ACTIVITY_LIST_URL, {"funder_id": self.funder.id})
        ids = {e["id"] for e in resp.data["results"]}
        self.assertIn(self.grant_a_entry.id, ids)

    def test_funder_filter_includes_applied_preregistration(self):
        resp = self.client.get(ACTIVITY_LIST_URL, {"funder_id": self.funder.id})
        ids = {e["id"] for e in resp.data["results"]}
        self.assertIn(self.applied_prereg_entry.id, ids)

    def test_funder_filter_includes_grant_where_funder_is_contact(self):
        resp = self.client.get(ACTIVITY_LIST_URL, {"funder_id": self.funder.id})
        ids = {e["id"] for e in resp.data["results"]}
        self.assertIn(self.grant_b_entry.id, ids)

    def test_funder_filter_excludes_unrelated_grants(self):
        resp = self.client.get(ACTIVITY_LIST_URL, {"funder_id": self.funder.id})
        ids = {e["id"] for e in resp.data["results"]}
        self.assertNotIn(self.grant_c_entry.id, ids)

    def test_funder_filter_excludes_pending_grants(self):
        resp = self.client.get(ACTIVITY_LIST_URL, {"funder_id": self.funder.id})
        ids = {e["id"] for e in resp.data["results"]}
        self.assertNotIn(self.grant_d_entry.id, ids)

    def test_funder_filter_includes_completed_grants(self):
        resp = self.client.get(ACTIVITY_LIST_URL, {"funder_id": self.funder.id})
        ids = {e["id"] for e in resp.data["results"]}
        self.assertIn(self.grant_e_entry.id, ids)

    def test_funder_filter_excludes_closed_grants(self):
        resp = self.client.get(ACTIVITY_LIST_URL, {"funder_id": self.funder.id})
        ids = {e["id"] for e in resp.data["results"]}
        self.assertNotIn(self.grant_f_entry.id, ids)

    def test_funder_filter_excludes_unrelated_preregistration(self):
        resp = self.client.get(ACTIVITY_LIST_URL, {"funder_id": self.funder.id})
        ids = {e["id"] for e in resp.data["results"]}
        self.assertNotIn(self.lone_prereg_entry.id, ids)

    def test_funder_filter_includes_comments_on_funder_grant(self):
        comment_entry = _make_feed_entry(
            RhCommentModel,
            object_id=11111,
            unified_document=self.grant_a_doc,
            user=self.applicant,
        )
        resp = self.client.get(ACTIVITY_LIST_URL, {"funder_id": self.funder.id})
        ids = {e["id"] for e in resp.data["results"]}
        self.assertIn(comment_entry.id, ids)

    def test_funder_filter_includes_comments_on_applied_prereg(self):
        comment_entry = _make_feed_entry(
            RhCommentModel,
            object_id=22222,
            unified_document=self.applied_prereg_doc,
            user=self.applicant,
        )
        resp = self.client.get(ACTIVITY_LIST_URL, {"funder_id": self.funder.id})
        ids = {e["id"] for e in resp.data["results"]}
        self.assertIn(comment_entry.id, ids)

    def test_funder_filter_nonexistent_funder(self):
        resp = self.client.get(ACTIVITY_LIST_URL, {"funder_id": 999999})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["results"]), 0)

    def test_funder_filter_funder_with_no_grants(self):
        no_grant_funder = create_test_user("no_grants", email="nogrants@example.com")
        resp = self.client.get(ACTIVITY_LIST_URL, {"funder_id": no_grant_funder.id})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["results"]), 0)

    def test_funder_filter_combined_with_content_type_comments(self):
        """funder_id + content_type=RHCOMMENTMODEL → only comments on
        funder's docs."""
        comment_on_grant = _make_feed_entry(
            RhCommentModel,
            object_id=33333,
            unified_document=self.grant_a_doc,
            user=self.applicant,
        )
        resp = self.client.get(
            ACTIVITY_LIST_URL,
            {"funder_id": self.funder.id, "content_type": "RHCOMMENTMODEL"},
        )
        ids = {e["id"] for e in resp.data["results"]}
        self.assertIn(comment_on_grant.id, ids)
        self.assertNotIn(self.grant_a_entry.id, ids)
        self.assertNotIn(self.applied_prereg_entry.id, ids)

    def test_funder_filter_combined_with_scope_peer_reviews(self):
        """funder_id + scope=peer_reviews → only peer review comments
        on funder's docs."""
        post_ct = ContentType.objects.get_for_model(ResearchhubPost)
        thread = RhCommentThreadModel.objects.create(
            thread_type=PEER_REVIEW,
            content_type=post_ct,
            object_id=self.applied_prereg_post.id,
            created_by=self.other_user,
        )
        peer_review = RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "peer review"}]},
            comment_type=PEER_REVIEW,
            created_by=self.other_user,
            thread=thread,
        )
        generic = RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "generic"}]},
            comment_type=GENERIC_COMMENT,
            created_by=self.other_user,
            thread=thread,
        )
        peer_review_entry = _make_feed_entry(
            RhCommentModel,
            object_id=peer_review.id,
            unified_document=self.applied_prereg_doc,
            user=self.other_user,
        )
        generic_entry = _make_feed_entry(
            RhCommentModel,
            object_id=generic.id,
            unified_document=self.applied_prereg_doc,
            user=self.other_user,
        )

        resp = self.client.get(
            ACTIVITY_LIST_URL,
            {"funder_id": self.funder.id, "scope": "peer_reviews"},
        )
        ids = {e["id"] for e in resp.data["results"]}
        self.assertIn(peer_review_entry.id, ids)
        self.assertNotIn(generic_entry.id, ids)
        self.assertNotIn(self.grant_a_entry.id, ids)

    def test_funder_filter_grant_id_takes_precedence(self):
        """If both funder_id and grant_id are passed, grant_id wins."""
        resp = self.client.get(
            ACTIVITY_LIST_URL,
            {"funder_id": self.funder.id, "grant_id": self.grant_b.id},
        )
        ids = {e["id"] for e in resp.data["results"]}
        # grant_b is in funder's set, but grant_id=grant_b should narrow
        # to grant_b's docs only (not grant_a or its applied prereg)
        self.assertIn(self.grant_b_entry.id, ids)
        self.assertNotIn(self.grant_a_entry.id, ids)
        self.assertNotIn(self.applied_prereg_entry.id, ids)

    def test_funder_filter_no_duplicates_when_creator_and_contact(self):
        """Funder being both creator and contact of the same grant
        should not produce duplicate feed entries."""
        self.grant_a.contacts.add(self.funder)
        resp = self.client.get(ACTIVITY_LIST_URL, {"funder_id": self.funder.id})
        ids = [e["id"] for e in resp.data["results"]]
        self.assertEqual(len(ids), len(set(ids)))
