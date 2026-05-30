from decimal import Decimal
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType

from feed.feed_list_dto import (
    FundingFeedListEntrySerializer,
    GrantFeedListEntrySerializer,
    GrantFeedPostSerializer,
)
from feed.models import FeedEntry
from purchase.models import Fundraise, Grant, GrantApplication, NonprofitFundraiseLink, NonprofitOrg
from purchase.related_models.constants.currency import USD
from researchhub_document.related_models.constants.document_type import GRANT, PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_default_user
from utils.test_helpers import AWSMockTestCase


class GrantFeedListDtoTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        self.user = create_random_default_user("grant_dto_user")
        self.grant_doc = ResearchhubUnifiedDocument.objects.create(document_type=GRANT)
        self.grant_post = ResearchhubPost.objects.create(
            title="Grant Post",
            created_by=self.user,
            document_type=GRANT,
            renderable_text="Grant body",
            unified_document=self.grant_doc,
        )
        self.grant = Grant.objects.create(
            created_by=self.user,
            unified_document=self.grant_doc,
            amount=Decimal("10000.00"),
            currency=USD,
            organization="Test Foundation",
            short_title="Test Grant",
            description="Grant description",
            status=Grant.OPEN,
        )

    def _make_feed_entry(self, post):
        return FeedEntry(
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=post.id,
            id=post.id,
            user=self.user,
            action="PUBLISH",
            action_date=post.created_date,
            unified_document=post.unified_document,
            item=post,
            metrics={"votes": 1, "replies": 0, "adjusted_score": 1},
        )

    @patch("purchase.related_models.rsc_exchange_rate_model.RscExchangeRate.usd_to_rsc")
    def test_grant_feed_list_entry_omits_heavy_envelope_fields(self, mock_usd_to_rsc):
        mock_usd_to_rsc.return_value = 200.0
        data = GrantFeedListEntrySerializer(self._make_feed_entry(self.grant_post)).data

        self.assertIn("content_object", data)
        self.assertNotIn("hot_score_v2", data)
        self.assertNotIn("created_date", data)
        self.assertNotIn("adjusted_score", data)

        content = data["content_object"]
        self.assertNotIn("bounties", content)
        self.assertNotIn("purchases", content)
        self.assertNotIn("renderable_text", content)
        grant_data = content["grant"]
        self.assertNotIn("contacts", grant_data)
        self.assertIn("amount", grant_data)
        self.assertIn("usd", grant_data["amount"])

    @patch("purchase.related_models.rsc_exchange_rate_model.RscExchangeRate.usd_to_rsc")
    def test_grant_application_fundraise_is_slim_without_key_insight(self, mock_usd_to_rsc):
        mock_usd_to_rsc.return_value = 200.0

        prereg_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        prereg_post = ResearchhubPost.objects.create(
            title="Applicant Proposal",
            created_by=self.user,
            document_type=PREREGISTRATION,
            renderable_text="Proposal",
            unified_document=prereg_doc,
        )
        Fundraise.objects.create(
            created_by=self.user,
            unified_document=prereg_doc,
            goal_amount=Decimal("5000.00"),
            goal_currency=USD,
            status=Fundraise.OPEN,
        )
        GrantApplication.objects.create(
            grant=self.grant, preregistration_post=prereg_post, applicant=self.user
        )

        grant_post = ResearchhubPost.objects.get(id=self.grant_post.id)
        data = GrantFeedPostSerializer(
            grant_post, context={"include_key_insights": False}
        ).data
        application = data["grant"]["applications"][0]

        self.assertNotIn("key_insight", application)
        fundraise = application["fundraise"]
        self.assertNotIn("contributors", fundraise)
        self.assertNotIn("amount_raised", fundraise)
        self.assertNotIn("status", fundraise)
        self.assertIn("goal_amount", fundraise)
        self.assertIn("reviews", fundraise)


class FundingFeedListDtoTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        self.user = create_random_default_user("funding_dto_user")

    @patch("purchase.related_models.rsc_exchange_rate_model.RscExchangeRate.usd_to_rsc")
    def test_funding_feed_list_entry_includes_post_id_on_associated_grants(
        self, mock_usd_to_rsc
    ):
        mock_usd_to_rsc.return_value = 200.0

        prereg_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        prereg_post = ResearchhubPost.objects.create(
            title="Funded Preregistration",
            created_by=self.user,
            document_type=PREREGISTRATION,
            renderable_text="Proposal",
            unified_document=prereg_doc,
        )
        Fundraise.objects.create(
            unified_document=prereg_doc,
            created_by=self.user,
            goal_amount=Decimal("500.00"),
            goal_currency=USD,
            status=Fundraise.OPEN,
        )

        grant_doc = ResearchhubUnifiedDocument.objects.create(document_type=GRANT)
        grant_post = ResearchhubPost.objects.create(
            title="Grant For Badge",
            created_by=self.user,
            document_type=GRANT,
            renderable_text="Grant",
            unified_document=grant_doc,
        )
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=grant_doc,
            amount=Decimal("10000.00"),
            currency=USD,
            organization="Test Foundation",
            short_title="Test Grant",
            description="Grant description",
            status=Grant.OPEN,
        )
        GrantApplication.objects.create(
            grant=grant, preregistration_post=prereg_post, applicant=self.user
        )

        prereg_post = ResearchhubPost.objects.prefetch_related(
            "grant_applications__grant__unified_document__posts"
        ).get(id=prereg_post.id)
        grant = prereg_post.grant_applications.first().grant
        grant.num_applicants = 1

        feed_entry = FeedEntry(
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=prereg_post.id,
            id=prereg_post.id,
            user=self.user,
            action="PUBLISH",
            action_date=prereg_post.created_date,
            unified_document=prereg_doc,
            item=prereg_post,
            metrics={"votes": 0, "replies": 0, "adjusted_score": 0},
        )

        grants = FundingFeedListEntrySerializer(feed_entry).data["associated_grants"]
        self.assertEqual(len(grants), 1)
        self.assertEqual(grants[0]["post_id"], grant_post.id)
        self.assertEqual(grants[0]["num_applicants"], 1)

    @patch("purchase.related_models.rsc_exchange_rate_model.RscExchangeRate.usd_to_rsc")
    def test_funding_nonprofit_is_slim(self, mock_usd_to_rsc):
        mock_usd_to_rsc.return_value = 200.0

        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        post = ResearchhubPost.objects.create(
            title="Nonprofit Proposal",
            created_by=self.user,
            document_type=PREREGISTRATION,
            renderable_text="Proposal",
            unified_document=unified_doc,
        )
        fundraise = Fundraise.objects.create(
            unified_document=unified_doc,
            created_by=self.user,
            goal_amount=Decimal("100.00"),
            goal_currency=USD,
            status=Fundraise.OPEN,
        )
        nonprofit = NonprofitOrg.objects.create(
            name="Test Nonprofit",
            ein="12-3456789",
            endaoment_org_id="endaoment-123",
        )
        NonprofitFundraiseLink.objects.create(fundraise=fundraise, nonprofit=nonprofit)

        feed_entry = FeedEntry(
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=post.id,
            id=post.id,
            user=self.user,
            action="PUBLISH",
            action_date=post.created_date,
            unified_document=unified_doc,
            item=post,
            metrics={"votes": 0, "replies": 0, "adjusted_score": 0},
        )

        nonprofit_data = FundingFeedListEntrySerializer(feed_entry).data["nonprofit"]
        self.assertEqual(nonprofit_data, {"id": nonprofit.id, "name": "Test Nonprofit"})
        self.assertNotIn("ein", nonprofit_data)

    @patch("purchase.related_models.rsc_exchange_rate_model.RscExchangeRate.usd_to_rsc")
    def test_funding_fundraise_contributors_omit_contribution_details(
        self, mock_usd_to_rsc
    ):
        mock_usd_to_rsc.return_value = 200.0

        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        post = ResearchhubPost.objects.create(
            title="Fundraise Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            renderable_text="Proposal",
            unified_document=unified_doc,
        )
        Fundraise.objects.create(
            unified_document=unified_doc,
            created_by=self.user,
            goal_amount=Decimal("100.00"),
            goal_currency=USD,
            status=Fundraise.OPEN,
        )

        feed_entry = FeedEntry(
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=post.id,
            id=post.id,
            user=self.user,
            action="PUBLISH",
            action_date=post.created_date,
            unified_document=unified_doc,
            item=post,
            metrics={"votes": 0, "replies": 0, "adjusted_score": 0},
        )

        content = FundingFeedListEntrySerializer(feed_entry).data["content_object"]
        top = content["fundraise"]["contributors"]["top"]
        for contributor in top:
            self.assertNotIn("contributions", contributor)
            self.assertNotIn("total_contribution", contributor)

    @patch("purchase.related_models.rsc_exchange_rate_model.RscExchangeRate.usd_to_rsc")
    def test_key_insight_included_only_when_requested(self, mock_usd_to_rsc):
        mock_usd_to_rsc.return_value = 200.0

        prereg_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        prereg_post = ResearchhubPost.objects.create(
            title="Applicant Proposal",
            created_by=self.user,
            document_type=PREREGISTRATION,
            renderable_text="Proposal",
            unified_document=prereg_doc,
        )
        Fundraise.objects.create(
            created_by=self.user,
            unified_document=prereg_doc,
            goal_amount=Decimal("5000.00"),
            goal_currency=USD,
            status=Fundraise.OPEN,
        )
        GrantApplication.objects.create(
            grant=self.grant, preregistration_post=prereg_post, applicant=self.user
        )

        grant_post = ResearchhubPost.objects.get(id=self.grant_post.id)
        without = GrantFeedPostSerializer(
            grant_post, context={"include_key_insights": False}
        ).data
        with_insights = GrantFeedPostSerializer(
            grant_post, context={"include_key_insights": True}
        ).data

        self.assertNotIn(
            "key_insight", without["grant"]["applications"][0]
        )
        self.assertIn("key_insight", with_insights["grant"]["applications"][0])
