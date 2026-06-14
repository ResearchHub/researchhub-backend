from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from feed.activity_feed_dto import (
    build_related_work,
    resolve_activity_bounty,
    resolve_activity_context,
    resolve_bounty_id_for_funding_activity,
    serialize_activity_bounty,
)
from feed.models import FeedEntry
from hub.tests.helpers import create_hub
from purchase.models import Fundraise, Grant
from reputation.models import Bounty, Escrow, EscrowRecipients
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
from user.related_models.funding_activity_model import FundingActivity
from user.tests.helpers import create_random_default_user
from utils.test_helpers import AWSMockTestCase


class BuildRelatedWorkTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        self.user = create_random_default_user("related_work_user")

    def test_preregistration_includes_fundraise_subset(self):
        # Arrange
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION,
        )
        hub = create_hub("related-work-hub")
        unified_doc.hubs.add(hub)
        ResearchhubPost.objects.create(
            title="Fundraising Proposal",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=unified_doc,
        )
        Fundraise.objects.create(
            unified_document=unified_doc,
            created_by=self.user,
            goal_amount=Decimal("1000.00"),
            goal_currency="USD",
            status=Fundraise.OPEN,
            end_date=timezone.now() + timezone.timedelta(days=30),
        )

        # Act
        data = build_related_work(unified_doc)

        # Assert
        self.assertEqual(data["document_type"], PREREGISTRATION)
        self.assertEqual(data["title"], "Fundraising Proposal")
        self.assertEqual(data["hub"]["slug"], hub.slug)
        self.assertIsNotNone(data["fundraise"])
        self.assertEqual(data["fundraise"]["status"], Fundraise.OPEN)
        self.assertIn("usd", data["fundraise"]["goal_amount"])
        self.assertIn("rsc", data["fundraise"]["amount_raised"])
        self.assertIsNotNone(data["fundraise"]["end_date"])
        self.assertIsNone(data["grant"])

    def test_grant_includes_grant_subset(self):
        # Arrange
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=GRANT,
        )
        post = ResearchhubPost.objects.create(
            title="Research Grant RFP",
            created_by=self.user,
            document_type=GRANT,
            unified_document=unified_doc,
        )
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=unified_doc,
            amount=Decimal("50000"),
            currency="USD",
            status=Grant.OPEN,
            organization="ResearchHub Foundation",
            end_date=timezone.now() + timezone.timedelta(days=60),
        )

        # Act
        data = build_related_work(unified_doc)

        # Assert
        self.assertEqual(data["id"], post.id)
        self.assertEqual(data["document_type"], GRANT)
        self.assertEqual(data["grant"]["id"], grant.id)
        self.assertEqual(data["grant"]["organization"], "ResearchHub Foundation")
        self.assertEqual(data["grant"]["amount"], str(grant.amount))
        self.assertEqual(data["grant"]["currency"], "USD")
        self.assertEqual(data["grant"]["num_applicants"], 0)
        self.assertIsNone(data["fundraise"])


class ActivityContextTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        self.user = create_random_default_user("activity_ctx_user")

    def _make_entry(self, model, object_id, unified_doc):
        ct = ContentType.objects.get_for_model(model)
        return FeedEntry.objects.create(
            content_type=ct,
            object_id=object_id,
            unified_document=unified_doc,
            user=self.user,
            action="PUBLISH",
            action_date=timezone.now(),
            content={},
            metrics={},
        )

    def test_funding_activity_tip_review_context(self):
        # Arrange
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION,
        )
        activity = FundingActivity.objects.create(
            funder=self.user,
            source_type=FundingActivity.TIP_REVIEW,
            total_amount=Decimal("10"),
            unified_document=unified_doc,
            activity_date=timezone.now(),
            source_content_type=ContentType.objects.get_for_model(self.user),
            source_object_id=self.user.id,
        )
        entry = self._make_entry(FundingActivity, activity.id, unified_doc)

        # Act
        context_value = resolve_activity_context(entry, item=activity)

        # Assert
        self.assertEqual(context_value, "tip_review")

    def test_comment_with_bounty_returns_bounty_opened(self):
        # Arrange
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION,
        )
        post = ResearchhubPost.objects.create(
            title="Bounty Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=unified_doc,
        )
        post_ct = ContentType.objects.get_for_model(ResearchhubPost)
        thread = RhCommentThreadModel.objects.create(
            content_type=post_ct,
            object_id=post.id,
            created_by=self.user,
        )
        comment = RhCommentModel.objects.create(
            thread=thread,
            created_by=self.user,
            comment_type=GENERIC_COMMENT,
            comment_content_json={"ops": [{"insert": "bounty comment"}]},
        )
        escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
            content_type=post_ct,
            object_id=post.id,
        )
        bounty = Bounty.objects.create(
            created_by=self.user,
            bounty_type=Bounty.Type.REVIEW,
            unified_document=unified_doc,
            item=comment,
            escrow=escrow,
            amount=Decimal("1510"),
            status=Bounty.OPEN,
        )
        entry = self._make_entry(RhCommentModel, comment.id, unified_doc)

        # Act
        context_value = resolve_activity_context(entry, item=comment)
        activity_bounty = resolve_activity_bounty(entry, item=comment)

        # Assert
        self.assertEqual(context_value, "bounty_opened")
        self.assertEqual(activity_bounty["id"], bounty.id)
        self.assertEqual(activity_bounty["bounty_type"], Bounty.Type.REVIEW)
        self.assertEqual(activity_bounty["amount"], str(bounty.amount))

    def test_peer_review_comment_context(self):
        # Arrange
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION,
        )
        post = ResearchhubPost.objects.create(
            title="Review Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=unified_doc,
        )
        post_ct = ContentType.objects.get_for_model(ResearchhubPost)
        thread = RhCommentThreadModel.objects.create(
            content_type=post_ct,
            object_id=post.id,
            created_by=self.user,
        )
        comment = RhCommentModel.objects.create(
            thread=thread,
            created_by=self.user,
            comment_type=PEER_REVIEW,
            comment_content_json={"ops": [{"insert": "peer review"}]},
        )
        entry = self._make_entry(RhCommentModel, comment.id, unified_doc)

        # Act
        context_value = resolve_activity_context(entry, item=comment)

        # Assert
        self.assertEqual(context_value, "peer_review_published")


class BountyIdForFundingActivityTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        self.funder = create_random_default_user("bounty_id_funder")
        self.recipient = create_random_default_user("bounty_id_recipient")
        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION,
        )
        self.post = ResearchhubPost.objects.create(
            title="Bounty Proposal",
            created_by=self.funder,
            document_type=PREREGISTRATION,
            unified_document=self.unified_doc,
        )

    def test_bounty_payout_resolves_bounty_id(self):
        # Arrange
        post_ct = ContentType.objects.get_for_model(ResearchhubPost)
        escrow = Escrow.objects.create(
            hold_type=Escrow.BOUNTY,
            status=Escrow.PAID,
            created_by=self.funder,
            content_type=post_ct,
            object_id=self.post.id,
        )
        bounty = Bounty.objects.create(
            created_by=self.funder,
            bounty_type=Bounty.Type.REVIEW,
            unified_document=self.unified_doc,
            item_content_type=post_ct,
            item_object_id=self.post.id,
            escrow=escrow,
            amount=Decimal("50"),
        )
        recipient = EscrowRecipients.objects.create(
            escrow=escrow,
            user=self.recipient,
            amount=Decimal("50"),
        )
        er_ct = ContentType.objects.get_for_model(EscrowRecipients)
        activity = FundingActivity.objects.create(
            funder=self.funder,
            source_type=FundingActivity.BOUNTY_PAYOUT,
            total_amount=Decimal("50"),
            unified_document=self.unified_doc,
            activity_date=timezone.now(),
            source_content_type=er_ct,
            source_object_id=recipient.id,
        )
        activity._prefetched_bounty_payout_source = recipient

        # Act
        bounty_id = resolve_bounty_id_for_funding_activity(activity)

        # Assert
        self.assertEqual(bounty_id, bounty.id)

    def test_tip_review_returns_none_bounty_id(self):
        # Arrange
        activity = FundingActivity.objects.create(
            funder=self.funder,
            source_type=FundingActivity.TIP_REVIEW,
            total_amount=Decimal("10"),
            unified_document=self.unified_doc,
            activity_date=timezone.now(),
            source_content_type=ContentType.objects.get_for_model(self.funder),
            source_object_id=self.funder.id,
        )

        # Act
        bounty_id = resolve_bounty_id_for_funding_activity(activity)

        # Assert
        self.assertIsNone(bounty_id)


class SerializeActivityBountyTests(AWSMockTestCase):
    def test_open_bounty_includes_expiration_date(self):
        # Arrange
        expiration = timezone.now() + timezone.timedelta(days=7)
        bounty = Bounty(
            id=41,
            amount=Decimal("1510"),
            bounty_type=Bounty.Type.REVIEW,
            status=Bounty.OPEN,
            expiration_date=expiration,
        )

        # Act
        data = serialize_activity_bounty(bounty)

        # Assert
        self.assertEqual(data["id"], 41)
        self.assertEqual(data["status"], Bounty.OPEN)
        self.assertEqual(data["expiration_date"], expiration)
