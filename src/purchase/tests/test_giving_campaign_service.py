from datetime import timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from hub.models import Hub
from purchase.models import Fundraise, GivingCampaign, GivingChallenge, Purchase
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.related_models.usd_fundraise_contribution_model import (
    UsdFundraiseContribution,
)
from purchase.services.giving_campaign_service import GivingCampaignService
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from user.tests.helpers import create_random_authenticated_user


class GivingCampaignServiceTests(TestCase):
    def setUp(self):
        self.service = GivingCampaignService()
        now = timezone.now()
        self.campaign = GivingCampaign.objects.create(
            slug="giving-tuesday",
            start_date=now - timedelta(hours=1),
            end_date=now + timedelta(hours=1),
            goal_usd=Decimal(1000),
        )
        self.hub = Hub.objects.create(name="Biology")
        researcher = create_random_authenticated_user("researcher")
        post = create_post(created_by=researcher, document_type=PREREGISTRATION)
        post.unified_document.hubs.add(self.hub)
        self.fundraise = Fundraise.objects.create(
            created_by=researcher,
            unified_document=post.unified_document,
            goal_amount=Decimal(1000),
        )
        RscExchangeRate.objects.create(
            rate=0.5, real_rate=0.5, price_source="COIN_GECKO", target_currency="USD"
        )

    def _give_usd(self, user, usd_cents, before_campaign=False):
        """Record a USD gift to the fundraise, optionally from before the campaign."""
        gift = UsdFundraiseContribution.objects.create(
            user=user,
            fundraise=self.fundraise,
            amount_cents=usd_cents,
            fee_cents=0,
            origin_fund_id="test-fund",
            destination_org_id="test-org",
        )
        if before_campaign:
            UsdFundraiseContribution.objects.filter(id=gift.id).update(
                created_date=self.campaign.start_date - timedelta(days=1)
            )

    def _create_challenge(self, **fields):
        """Create a challenge that runs for the whole campaign."""
        return GivingChallenge.objects.create(
            campaign=self.campaign,
            name="Challenge",
            sponsor="ResearchHub",
            start_date=self.campaign.start_date,
            end_date=self.campaign.end_date,
            **fields,
        )

    def test_sums_gifts_and_donors_inside_campaign(self):
        """Gifts inside the campaign count at their RSC rate, earlier gifts do not."""
        # Arrange
        self._give_usd(create_random_authenticated_user("usd_donor"), 2000)
        Purchase.objects.create(
            user=create_random_authenticated_user("rsc_donor"),
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=self.fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            purchase_method=Purchase.OFF_CHAIN,
            amount="100",
            rsc_usd_rate=0.5,
        )
        self._give_usd(
            create_random_authenticated_user("early_donor"), 3000, before_campaign=True
        )

        # Act
        summary = self.service.summarize_campaign(self.campaign)

        # Assert
        self.assertEqual(summary["given_usd"], 70.0)
        self.assertEqual(summary["donor_count"], 2)

    def test_caps_match_at_challenge_amount(self):
        """A match stops at its cap and completes once gifts to its hub reach it."""
        # Arrange
        self._create_challenge(
            kind=GivingChallenge.Kind.MATCH, hub=self.hub, amount_usd=Decimal(25)
        )
        self._give_usd(create_random_authenticated_user("donor"), 4000)

        # Act
        [challenge] = self.service.summarize_campaign(self.campaign)["challenges"]

        # Assert
        self.assertEqual(challenge["matched_usd"], 25.0)
        self.assertTrue(challenge["is_completed"])

    def test_counts_only_first_time_donors_for_unlock(self):
        """A first-time unlock skips donors who gave before it started."""
        # Arrange
        self._create_challenge(
            kind=GivingChallenge.Kind.UNLOCK,
            amount_usd=Decimal(500),
            donor_goal=2,
            first_time_donors_only=True,
        )
        returning_donor = create_random_authenticated_user("returning_donor")
        self._give_usd(returning_donor, 1000, before_campaign=True)
        self._give_usd(returning_donor, 1000)
        self._give_usd(create_random_authenticated_user("new_donor"), 1000)

        # Act
        [challenge] = self.service.summarize_campaign(self.campaign)["challenges"]

        # Assert
        self.assertEqual(challenge["donor_count"], 1)
        self.assertFalse(challenge["is_completed"])
