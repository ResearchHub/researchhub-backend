from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from research_ai.models import Expert, ExpertSearch, GeneratedEmail, SearchExpert
from research_ai.services.invited_experts_service import (
    _safe_rate,
    get_invited_expert_editors_overview,
    get_invited_expert_overview,
)
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from user.tests.helpers import create_hub_editor, create_random_authenticated_user


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
        create_post(created_by=user, document_type=PREREGISTRATION)

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
        self.assertEqual(result.counts.proposals_opened, 1)

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

    def test_editors_overview_aggregates(self):
        editor, _ = create_hub_editor("stats_editor", "stats_hub")
        prereg_a = create_post(created_by=editor, document_type=PREREGISTRATION)
        prereg_b = create_post(created_by=editor, document_type=PREREGISTRATION)
        search_a = ExpertSearch.objects.create(
            created_by=editor,
            unified_document_id=prereg_a.unified_document_id,
            query="A",
            status=ExpertSearch.Status.COMPLETED,
        )
        search_b = ExpertSearch.objects.create(
            created_by=editor,
            unified_document_id=prereg_b.unified_document_id,
            query="B",
            status=ExpertSearch.Status.COMPLETED,
        )
        search_dup = ExpertSearch.objects.create(
            created_by=editor,
            unified_document_id=prereg_a.unified_document_id,
            query="A duplicate doc",
            status=ExpertSearch.Status.COMPLETED,
        )
        for i in range(3):
            expert = Expert.objects.create(email=f"ed_{i}@example.com")
            SearchExpert.objects.create(
                expert_search=search_a, expert=expert, position=i
            )
        for i, search in enumerate((search_a, search_b, search_dup)):
            GeneratedEmail.objects.create(
                created_by=editor,
                expert_search=search,
                expert_email=f"outreach_{i}@example.com",
                status=GeneratedEmail.Status.SENT,
            )

        start = timezone.now() - timedelta(days=1)
        end = timezone.now()
        overview = get_invited_expert_editors_overview(
            unified_document_id=None,
            start=start,
            end=end,
            limit=5,
        )
        self.assertEqual(overview.total, 1)
        row = overview.items[0]
        self.assertEqual(row.experts_total, 3)
        self.assertEqual(row.proposals_outreach_count, 2)
        self.assertEqual(row.emails_sent, 3)
        self.assertEqual(
            row.emails_sent_by_proposal,
            {
                prereg_a.unified_document_id: 2,
                prereg_b.unified_document_id: 1,
            },
        )
