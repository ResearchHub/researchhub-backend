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
from researchhub_document.related_models.constants.document_type import GRANT, PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import ResearchhubUnifiedDocument

User = get_user_model()


class StatusPrioritySortingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="testuser", password="testpass")  # NOSONAR
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.now = timezone.now()
        self.counter = 0
        
        RscExchangeRate.objects.create(
            price_source=MORALIS, rate=3.0, real_rate=3.0, target_currency=USD
        )

    def _create_fundraise(self, status, days_offset):
        self.counter += 1
        doc = ResearchhubUnifiedDocument.objects.create(document_type=PREREGISTRATION)
        post = ResearchhubPost.objects.create(
            title=f"Post {self.counter}",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=doc,
            renderable_text="Test",
            slug=f"test-{self.counter}",
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

    def _create_grant(self, status, days_offset):
        self.counter += 1
        doc = ResearchhubUnifiedDocument.objects.create(document_type=GRANT)
        post = ResearchhubPost.objects.create(
            title=f"Grant {self.counter}",
            created_by=self.user,
            document_type=GRANT,
            unified_document=doc,
            renderable_text="Test",
            slug=f"grant-{self.counter}",
        )
        Grant.objects.create(
            created_by=self.user,
            unified_document=doc,
            status=status,
            amount=10000,
            description="Test",
            end_date=self.now + timedelta(days=days_offset),
        )
        return post

    def _get_ids(self, response):
        return [item["content_object"]["id"] for item in response.data["results"]]

    def test_show_open_fundraises_before_closed(self):
        open_post = self._create_fundraise(Fundraise.OPEN, 10)
        closed_post = self._create_fundraise(Fundraise.COMPLETED, -5)
        
        response = self.client.get(reverse("funding_feed-list"))
        ids = self._get_ids(response)
        
        self.assertLess(ids.index(open_post.id), ids.index(closed_post.id))

    def test_show_open_grants_before_closed(self):
        open_grant = self._create_grant(Grant.OPEN, 10)
        closed_grant = self._create_grant(Grant.CLOSED, -5)
        
        response = self.client.get(reverse("grant_feed-list"))
        ids = self._get_ids(response)
        
        self.assertLess(ids.index(open_grant.id), ids.index(closed_grant.id))

    def test_open_before_closed_across_all_orderings(self):
        open_post = self._create_fundraise(Fundraise.OPEN, 10)
        closed_post = self._create_fundraise(Fundraise.COMPLETED, -5)
        
        for ordering in ["amount_raised", "hot_score", "upvotes"]:
            response = self.client.get(f"{reverse('funding_feed-list')}?ordering={ordering}")
            ids = self._get_ids(response)
            
            self.assertLess(ids.index(open_post.id), ids.index(closed_post.id))

    def test_closed_sorted_most_recent_deadline_first(self):
        recent = self._create_fundraise(Fundraise.COMPLETED, -5)
        older = self._create_fundraise(Fundraise.COMPLETED, -30)
        
        response = self.client.get(f"{reverse('funding_feed-list')}?fundraise_status=CLOSED")
        ids = self._get_ids(response)
        
        self.assertLess(ids.index(older.id), ids.index(recent.id))
