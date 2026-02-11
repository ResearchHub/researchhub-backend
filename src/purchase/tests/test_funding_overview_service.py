from datetime import timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from purchase.models import Fundraise, Grant, Purchase
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.related_models.usd_fundraise_contribution_model import UsdFundraiseContribution
from purchase.services.funding_overview_service import FundingOverviewService
from researchhub_comment.constants.rh_comment_thread_types import AUTHOR_UPDATE
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT as GRANT_DOC_TYPE,
    PREREGISTRATION,
)
from user.tests.helpers import create_random_authenticated_user


class TestFundingOverviewService(TestCase):
    def setUp(self):
        self.service = FundingOverviewService()
        self.user = create_random_authenticated_user("funder", moderator=True)
        RscExchangeRate.objects.create(rate=0.5, real_rate=0.5, price_source="COIN_GECKO", target_currency="USD")

    def test_returns_expected_structure_with_zeros_for_new_user(self):
        # Arrange - uses setUp

        # Act
        result = self.service.get_funding_overview(self.user)

        # Assert
        self.assertEqual(result["total_distributed_usd"], 0.0)
        self.assertEqual(result["matched_funding_usd"], 0.0)
        self.assertEqual(result["total_applicants"], {"total": 0, "active": 0, "previous": 0})
        self.assertEqual(result["proposals_funded"], 0)
        self.assertEqual(result["recent_updates"], 0)
        self.assertEqual(result["active_grants"], {"active": 0, "total": 0})

    def test_active_grants_counts_correctly(self):
        # Arrange
        post = create_post(created_by=self.user, document_type=GRANT_DOC_TYPE)
        Grant.objects.create(created_by=self.user, unified_document=post.unified_document, amount=Decimal("1000"), status=Grant.OPEN)  # Active: open
        Grant.objects.create(created_by=self.user, unified_document=post.unified_document, amount=Decimal("1000"), status=Grant.CLOSED)  # Inactive: closed
        Grant.objects.create(created_by=self.user, unified_document=post.unified_document, amount=Decimal("1000"), status=Grant.OPEN, end_date=timezone.now() - timedelta(days=1))  # Inactive: expired

        # Act
        result = self.service._active_grants(self.user)

        # Assert
        self.assertEqual(result, {"active": 1, "total": 3})

    def test_queryset_sum_usd_combines_rsc_and_usd(self):
        # Arrange
        contributor = create_random_authenticated_user("contributor")
        post = create_post(created_by=self.user, document_type=PREREGISTRATION)
        fundraise = Fundraise.objects.create(created_by=self.user, unified_document=post.unified_document, goal_amount=Decimal("1000"), goal_currency="USD")
        Purchase.objects.create(user=contributor, content_type=ContentType.objects.get_for_model(Fundraise), object_id=fundraise.id, purchase_type=Purchase.FUNDRAISE_CONTRIBUTION, amount=100)  # 100 RSC * 0.5 = $50
        UsdFundraiseContribution.objects.create(user=contributor, fundraise=fundraise, amount_cents=10000, fee_cents=0)  # $100

        # Act
        rsc_usd = Purchase.objects.funding_contributions().for_fundraises([fundraise.id]).sum_usd()
        usd = UsdFundraiseContribution.objects.not_refunded().for_fundraises([fundraise.id]).sum_usd()

        # Assert
        self.assertEqual(round(rsc_usd + usd, 2), 150.0)
        self.assertEqual(Purchase.objects.funding_contributions().for_fundraises([]).sum_usd(), 0.0)

    def test_queryset_filters_and_excludes_users(self):
        # Arrange
        user1 = create_random_authenticated_user("user1")
        user2 = create_random_authenticated_user("user2")
        post = create_post(created_by=self.user, document_type=PREREGISTRATION)
        fundraise = Fundraise.objects.create(created_by=self.user, unified_document=post.unified_document, goal_amount=Decimal("1000"), goal_currency="USD")
        fundraise_ct = ContentType.objects.get_for_model(Fundraise)
        Purchase.objects.create(user=user1, content_type=fundraise_ct, object_id=fundraise.id, purchase_type=Purchase.FUNDRAISE_CONTRIBUTION, amount=100)
        Purchase.objects.create(user=user2, content_type=fundraise_ct, object_id=fundraise.id, purchase_type=Purchase.FUNDRAISE_CONTRIBUTION, amount=200)

        # Act & Assert - user1 only: 100 * 0.5 = $50
        self.assertEqual(Purchase.objects.for_user(user1.id).funding_contributions().for_fundraises([fundraise.id]).sum_usd(), 50.0)
        # exclude user1: 200 * 0.5 = $100
        self.assertEqual(Purchase.objects.funding_contributions().for_fundraises([fundraise.id]).exclude_user(user1.id).sum_usd(), 100.0)

    def test_update_count_filters_by_date(self):
        # Arrange
        post = create_post(created_by=self.user, document_type=PREREGISTRATION)
        thread = RhCommentThreadModel.objects.create(thread_type=AUTHOR_UPDATE, content_object=post, created_by=self.user)
        RhCommentModel.objects.create(thread=thread, created_by=self.user, comment_content_json={}, comment_type=AUTHOR_UPDATE)  # Recent
        old = RhCommentModel.objects.create(thread=thread, created_by=self.user, comment_content_json={}, comment_type=AUTHOR_UPDATE)
        RhCommentModel.objects.filter(id=old.id).update(created_date=timezone.now() - timedelta(days=60))  # Old

        # Act
        result = self.service._update_count([post.id], 30)

        # Assert
        self.assertEqual(result, 1)
        self.assertEqual(self.service._update_count([], 30), 0)
