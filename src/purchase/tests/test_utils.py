from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from purchase.models import Fundraise, Purchase
from purchase.related_models.usd_fundraise_contribution_model import UsdFundraiseContribution
from purchase.utils import get_funded_fundraise_ids
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_authenticated_user


class TestGetFundedFundraiseIds(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("funder")
        self.doc = ResearchhubUnifiedDocument.objects.create(document_type=PREREGISTRATION)
        self.ct = ContentType.objects.get_for_model(Fundraise)

    def _create_fundraise(self):
        return Fundraise.objects.create(
            created_by=self.user,
            unified_document=self.doc,
            goal_amount=100,
            goal_currency="USD",
            status=Fundraise.OPEN,
        )

    def _add_rsc_contribution(self, fundraise):
        Purchase.objects.create(
            user=self.user,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            content_type=self.ct,
            object_id=fundraise.id,
            amount=50,
        )

    def _add_usd_contribution(self, fundraise, is_refunded=False):
        UsdFundraiseContribution.objects.create(
            user=self.user,
            fundraise=fundraise,
            amount_cents=5000,
            is_refunded=is_refunded,
        )

    def test_returns_empty_for_no_contributions(self):
        # Arrange
        other_user = create_random_authenticated_user("other")

        # Act
        result = get_funded_fundraise_ids(other_user.id)

        # Assert
        self.assertEqual(result, set())

    def test_returns_rsc_and_usd_contributions_deduplicated(self):
        # Arrange
        fundraise = self._create_fundraise()
        self._add_rsc_contribution(fundraise)
        self._add_usd_contribution(fundraise)

        # Act
        result = get_funded_fundraise_ids(self.user.id)

        # Assert
        self.assertEqual(result, {fundraise.id})

    def test_excludes_refunded_usd_contributions(self):
        # Arrange
        fundraise = self._create_fundraise()
        self._add_usd_contribution(fundraise, is_refunded=True)

        # Act
        result = get_funded_fundraise_ids(self.user.id)

        # Assert
        self.assertEqual(result, set())

