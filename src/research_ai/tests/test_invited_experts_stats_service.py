from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from research_ai.models import Expert, ExpertSearch, GeneratedEmail, SearchExpert
from research_ai.services.invited_experts_service import (
    _safe_rate,
    get_invited_expert_editors_overview,
    get_invited_expert_overview,
)
from user.tests.helpers import create_random_authenticated_user


class InvitedExpertsStatsServiceTests(TestCase):
    def test_safe_rate_returns_none_for_zero_denominator(self):
        self.assertIsNone(_safe_rate(1, 0))

    def test_overview_summary_rates(self):
        user = create_random_authenticated_user("svc_rates", moderator=True)
        search = ExpertSearch.objects.create(
            created_by=user,
            query="Rates",
            status=ExpertSearch.Status.COMPLETED,
        )
        expert = Expert.objects.create(
            email="rates@example.com",
            registered_user=user,
        )
        SearchExpert.objects.create(expert_search=search, expert=expert, position=0)
        GeneratedEmail.objects.create(
            created_by=user,
            expert_search=search,
            expert_email="rates@example.com",
            status=GeneratedEmail.Status.SENT,
            opened_at=timezone.now(),
        )

        start = timezone.now() - timedelta(days=1)
        end = timezone.now()
        result = get_invited_expert_overview(
            unified_document_id=None,
            start=start,
            end=end,
        )
        self.assertEqual(result.summary.signup_rate, 1.0)
        self.assertEqual(result.summary.email_send_rate, 1.0)
        self.assertEqual(result.summary.open_rate, 1.0)

    def test_editors_overview_empty(self):
        start = timezone.now() - timedelta(days=1)
        end = timezone.now()
        overview = get_invited_expert_editors_overview(
            unified_document_id=None,
            start=start,
            end=end,
        )
        self.assertEqual(overview.total, 0)
        self.assertEqual(overview.items, [])
