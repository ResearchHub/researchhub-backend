"""
Tests for status-priority sorting in funding feeds.
Verifies that OPEN fundraises/grants always appear before CLOSED/COMPLETED ones.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from purchase.related_models.constants.currency import USD
from purchase.related_models.constants.rsc_exchange_currency import MORALIS
from purchase.related_models.fundraise_model import Fundraise
from purchase.related_models.grant_model import Grant
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.models import Escrow
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)

User = get_user_model()


class StatusPrioritySortingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="testuser", password="testpass")  # NOSONAR - test password
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.now = timezone.now()
        self.post_counter = 0
        
        RscExchangeRate.objects.create(
            price_source=MORALIS,
            rate=3.0,
            real_rate=3.0,
            target_currency=USD,
        )
    
    def tearDown(self):
        cache.clear()

    def _create_fundraise_post(self, title, status, days_offset):
        self.post_counter += 1
        doc = ResearchhubUnifiedDocument.objects.create(document_type=PREREGISTRATION)
        post = ResearchhubPost.objects.create(
            title=title,
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=doc,
            renderable_text=f"Test fundraise post {title}",
            slug=f"test-fundraise-{self.post_counter}",
            created_date=self.now,
        )
        escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.FUNDRAISE,
            amount_holding=100,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=doc.id,
        )
        Fundraise.objects.create(
            created_by=self.user,
            unified_document=doc,
            status=status,
            end_date=self.now + timedelta(days=days_offset),
            escrow=escrow,
        )
        return post

    def _create_grant_post(self, title, status, days_offset):
        self.post_counter += 1
        doc = ResearchhubUnifiedDocument.objects.create(document_type=GRANT)
        post = ResearchhubPost.objects.create(
            title=title,
            created_by=self.user,
            document_type=GRANT,
            unified_document=doc,
            renderable_text=f"Test grant post {title}",
            slug=f"test-grant-{self.post_counter}",
            created_date=self.now,
        )
        Grant.objects.create(
            created_by=self.user,
            unified_document=doc,
            status=status,
            amount=10000,
            description="Test grant",
            end_date=self.now + timedelta(days=days_offset),
        )
        return post

    def _get_post_ids(self, response):
        return [item["content_object"]["id"] for item in response.data["results"]]

    def test_proposals_tab_open_before_closed_with_amount_raised(self):
        """Proposals tab: OPEN fundraises appear before CLOSED when ordering by amount_raised"""
        open_post = self._create_fundraise_post("Open Proposal", Fundraise.OPEN, 10)
        closed_post = self._create_fundraise_post(
            "Closed Proposal", Fundraise.COMPLETED, -5
        )

        response = self.client.get(
            reverse("funding_feed-list")
            + "?ordering=amount_raised"
        )

        post_ids = self._get_post_ids(response)
        self.assertIn(open_post.id, post_ids, "Open post should be in results")
        self.assertIn(closed_post.id, post_ids, "Closed post should be in results")
        self.assertLess(post_ids.index(open_post.id), post_ids.index(closed_post.id))

    def test_proposals_tab_open_before_closed_with_hot_score(self):
        """Proposals tab: OPEN before CLOSED when ordering by hot_score"""
        open_post = self._create_fundraise_post("Open Hot", Fundraise.OPEN, 10)
        closed_post = self._create_fundraise_post("Closed Hot", Fundraise.COMPLETED, -5)

        response = self.client.get(
            reverse("funding_feed-list") + "?ordering=hot_score"
        )

        post_ids = self._get_post_ids(response)
        self.assertIn(open_post.id, post_ids)
        self.assertIn(closed_post.id, post_ids)
        self.assertLess(post_ids.index(open_post.id), post_ids.index(closed_post.id))

    def test_proposals_tab_open_before_closed_default_ordering(self):
        """Proposals tab: OPEN before CLOSED with default (newest) ordering"""
        open_recent = self._create_fundraise_post(
            "Open Recent", Fundraise.OPEN, 5
        )
        closed_old = self._create_fundraise_post(
            "Closed Old", Fundraise.COMPLETED, -30
        )

        response = self.client.get(
            reverse("funding_feed-list")
        )

        post_ids = self._get_post_ids(response)
        self.assertIn(open_recent.id, post_ids)
        self.assertIn(closed_old.id, post_ids)
        self.assertLess(
            post_ids.index(open_recent.id), post_ids.index(closed_old.id)
        )

    def test_request_for_proposals_open_before_closed(self):
        """Request for Proposals tab: OPEN grants appear before CLOSED grants"""
        open_grant = self._create_grant_post("Open RFP", Grant.OPEN, 10)
        closed_grant = self._create_grant_post("Closed RFP", Grant.CLOSED, -5)

        response = self.client.get(reverse("grant_feed-list"))

        post_ids = self._get_post_ids(response)
        self.assertIn(open_grant.id, post_ids)
        self.assertIn(closed_grant.id, post_ids)
        self.assertLess(
            post_ids.index(open_grant.id), post_ids.index(closed_grant.id)
        )

    def test_all_tab_open_before_closed(self):
        """All tab: OPEN fundraises appear before CLOSED fundraises"""
        open_post = self._create_fundraise_post("Open All", Fundraise.OPEN, 10)
        closed_post = self._create_fundraise_post("Closed All", Fundraise.COMPLETED, -5)

        response = self.client.get(reverse("funding_feed-list"))

        post_ids = self._get_post_ids(response)
        self.assertIn(open_post.id, post_ids)
        self.assertIn(closed_post.id, post_ids)
        self.assertLess(post_ids.index(open_post.id), post_ids.index(closed_post.id))

    def test_upvotes_ordering_open_before_closed(self):
        """Test upvotes ordering maintains OPEN before CLOSED status priority"""
        open_post = self._create_fundraise_post("Open Upvoted", Fundraise.OPEN, 10)
        closed_post = self._create_fundraise_post("Closed Upvoted", Fundraise.COMPLETED, -5)

        response = self.client.get(
            reverse("funding_feed-list") + "?ordering=upvotes"
        )

        post_ids = self._get_post_ids(response)
        self.assertIn(open_post.id, post_ids)
        self.assertIn(closed_post.id, post_ids)
        self.assertLess(post_ids.index(open_post.id), post_ids.index(closed_post.id))

    def test_multiple_closed_sorted_by_recent_first(self):
        """Within CLOSED fundraises, sort by most recent deadline first"""
        recent_closed = self._create_fundraise_post(
            "Recent Closed", Fundraise.COMPLETED, -5
        )
        old_closed = self._create_fundraise_post(
            "Old Closed", Fundraise.COMPLETED, -30
        )

        response = self.client.get(
            reverse("funding_feed-list") + "?fundraise_status=CLOSED"
        )

        post_ids = self._get_post_ids(response)
        self.assertIn(recent_closed.id, post_ids)
        self.assertIn(old_closed.id, post_ids)
        self.assertLess(
            post_ids.index(recent_closed.id), post_ids.index(old_closed.id)
        )

