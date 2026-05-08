from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from research_ai.models import Expert, ExpertSearch, GeneratedEmail, SearchExpert
from research_ai.services.invited_experts_service import (
    get_document_invite_candidates_for_email,
    get_invited_rows_for_unified_document,
)
from user.tests.helpers import create_user


class GetDocumentInviteCandidatesForEmailTests(TestCase):
    def setUp(self):
        from paper.tests.helpers import create_paper

        self.user = create_user(email="creator@test.com")
        self.paper = create_paper(
            title="Candidate doc",
            paper_publish_date="2021-01-01",
        )
        self.ud_id = self.paper.unified_document_id

    def test_empty_email_returns_empty(self):
        now = timezone.now()
        self.assertEqual(get_document_invite_candidates_for_email("", now), [])
        self.assertEqual(get_document_invite_candidates_for_email("   ", now), [])

    def test_no_generated_emails_in_window_returns_empty(self):
        self.assertEqual(
            get_document_invite_candidates_for_email(
                "expert@example.com", timezone.now()
            ),
            [],
        )

    def test_generated_email_in_window_returns_candidate(self):
        first_seen = timezone.now() - timedelta(days=2)
        search = ExpertSearch.objects.create(
            created_by=self.user,
            unified_document_id=self.ud_id,
            query="Test",
            status=ExpertSearch.Status.COMPLETED,
            completed_at=first_seen,
        )
        ge = GeneratedEmail.objects.create(
            created_by=self.user,
            expert_search=search,
            expert_email="expert@example.com",
            created_date=first_seen,
        )
        candidates = get_document_invite_candidates_for_email(
            "expert@example.com", timezone.now()
        )
        self.assertEqual(len(candidates), 1)
        doc_id, es_id, ge_id = candidates[0]
        self.assertEqual(doc_id, self.ud_id)
        self.assertEqual(es_id, search.id)
        self.assertEqual(ge_id, ge.id)

    def test_closed_generated_email_excluded_from_candidates(self):
        first_seen = timezone.now() - timedelta(days=2)
        search = ExpertSearch.objects.create(
            created_by=self.user,
            unified_document_id=self.ud_id,
            query="Test",
            status=ExpertSearch.Status.COMPLETED,
            completed_at=first_seen,
        )
        GeneratedEmail.objects.create(
            created_by=self.user,
            expert_search=search,
            expert_email="closed@example.com",
            created_date=first_seen,
            status=GeneratedEmail.Status.CLOSED,
        )
        self.assertEqual(
            get_document_invite_candidates_for_email(
                "closed@example.com", timezone.now()
            ),
            [],
        )

    def test_case_insensitive_email_match(self):
        first_seen = timezone.now() - timedelta(days=2)
        search = ExpertSearch.objects.create(
            created_by=self.user,
            unified_document_id=self.ud_id,
            query="Test",
            status=ExpertSearch.Status.COMPLETED,
            completed_at=first_seen,
        )
        GeneratedEmail.objects.create(
            created_by=self.user,
            expert_search=search,
            expert_email="Expert@Example.COM",
            created_date=first_seen,
        )
        candidates = get_document_invite_candidates_for_email(
            "expert@example.com", timezone.now()
        )
        self.assertEqual(len(candidates), 1)

    def test_generated_email_outside_window_excluded(self):
        """GeneratedEmail created 10 days ago is outside invite window."""
        first_seen = timezone.now() - timedelta(days=10)
        search = ExpertSearch.objects.create(
            created_by=self.user,
            unified_document_id=self.ud_id,
            query="Test",
            status=ExpertSearch.Status.COMPLETED,
            completed_at=first_seen,
        )
        ge = GeneratedEmail.objects.create(
            created_by=self.user,
            expert_search=search,
            expert_email="old@example.com",
        )
        GeneratedEmail.objects.filter(pk=ge.pk).update(created_date=first_seen)
        candidates = get_document_invite_candidates_for_email(
            "old@example.com", timezone.now()
        )
        self.assertEqual(len(candidates), 0)

    def test_generated_email_adds_candidate_with_generated_email_id(self):
        first_seen = timezone.now() - timedelta(days=1)
        search = ExpertSearch.objects.create(
            created_by=self.user,
            unified_document_id=self.ud_id,
            query="Test",
            status=ExpertSearch.Status.COMPLETED,
            completed_at=first_seen,
        )
        ge = GeneratedEmail.objects.create(
            created_by=self.user,
            expert_search=search,
            expert_email="ge@example.com",
            created_date=first_seen,
        )
        candidates = get_document_invite_candidates_for_email(
            "ge@example.com", timezone.now()
        )
        self.assertEqual(len(candidates), 1)
        _, es_id, ge_id = candidates[0]
        self.assertEqual(es_id, search.id)
        self.assertEqual(ge_id, ge.id)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class InvitedExpertsSignalTests(TestCase):
    """Signup links ``Expert.registered_user`` when outreach qualifies."""

    def setUp(self):
        from paper.tests.helpers import create_paper

        self.creator = create_user(email="creator@signal.test")
        self.paper = create_paper(
            title="Signal doc",
            paper_publish_date="2021-01-01",
        )
        self.ud_id = self.paper.unified_document_id

    def test_user_created_with_email_in_generated_email_within_7_days_links_expert(
        self,
    ):
        first_seen = timezone.now() - timedelta(days=3)
        search = ExpertSearch.objects.create(
            created_by=self.creator,
            unified_document_id=self.ud_id,
            query="Test",
            status=ExpertSearch.Status.COMPLETED,
            completed_at=first_seen,
        )
        ex = Expert.objects.create(
            email="invited@example.com",
            first_name="Inv",
            last_name="Expert",
        )
        SearchExpert.objects.create(expert_search=search, expert=ex, position=0)
        GeneratedEmail.objects.create(
            created_by=self.creator,
            expert_search=search,
            expert_email="invited@example.com",
            created_date=first_seen,
        )
        new_user = create_user(
            email="invited@example.com",
            first_name="Invited",
            last_name="User",
        )
        ex.refresh_from_db()
        self.assertEqual(ex.registered_user_id, new_user.id)
        rows = get_invited_rows_for_unified_document(self.ud_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].user.id, new_user.id)

    def test_user_created_sets_expert_registered_user_when_expert_row_exists(self):
        first_seen = timezone.now() - timedelta(days=2)
        search = ExpertSearch.objects.create(
            created_by=self.creator,
            unified_document_id=self.ud_id,
            query="Test",
            status=ExpertSearch.Status.COMPLETED,
            completed_at=first_seen,
        )
        GeneratedEmail.objects.create(
            created_by=self.creator,
            expert_search=search,
            expert_email="linkedexpert@example.com",
            created_date=first_seen,
        )
        Expert.objects.create(
            email="linkedexpert@example.com",
            first_name="Link",
            last_name="Expert",
        )
        new_user = create_user(
            email="linkedexpert@example.com",
            first_name="Link",
            last_name="User",
        )
        expert = Expert.objects.get(email="linkedexpert@example.com")
        expert.refresh_from_db()
        self.assertEqual(expert.registered_user_id, new_user.id)

    def test_user_created_after_7_days_does_not_link_expert(self):
        first_seen = timezone.now() - timedelta(days=10)
        search = ExpertSearch.objects.create(
            created_by=self.creator,
            unified_document_id=self.ud_id,
            query="Test",
            status=ExpertSearch.Status.COMPLETED,
            completed_at=first_seen,
        )
        ex = Expert.objects.create(
            email="late@example.com",
            first_name="Late",
            last_name="Expert",
        )
        SearchExpert.objects.create(expert_search=search, expert=ex, position=0)
        ge = GeneratedEmail.objects.create(
            created_by=self.creator,
            expert_search=search,
            expert_email="late@example.com",
        )
        GeneratedEmail.objects.filter(pk=ge.pk).update(created_date=first_seen)
        new_user = create_user(
            email="late@example.com",
            first_name="Late",
            last_name="User",
        )
        ex.refresh_from_db()
        self.assertIsNone(ex.registered_user_id)
        self.assertEqual(
            len(get_invited_rows_for_unified_document(self.ud_id)),
            0,
        )

    def test_user_created_email_not_in_any_search_does_not_link(self):
        create_user(
            email="stranger@example.com",
            first_name="Stranger",
            last_name="User",
        )
        self.assertEqual(len(get_invited_rows_for_unified_document(self.ud_id)), 0)

    def test_case_insensitive_email_links_expert(self):
        first_seen = timezone.now() - timedelta(days=2)
        search = ExpertSearch.objects.create(
            created_by=self.creator,
            unified_document_id=self.ud_id,
            query="Test",
            status=ExpertSearch.Status.COMPLETED,
            completed_at=first_seen,
        )
        ex = Expert.objects.create(
            email="case@test.com",
            first_name="Case",
            last_name="Expert",
        )
        SearchExpert.objects.create(expert_search=search, expert=ex, position=0)
        GeneratedEmail.objects.create(
            created_by=self.creator,
            expert_search=search,
            expert_email="Case@Test.com",
            created_date=first_seen,
        )
        new_user = create_user(
            email="case@test.com", first_name="Case", last_name="User"
        )
        ex.refresh_from_db()
        self.assertEqual(ex.registered_user_id, new_user.id)
        self.assertEqual(len(get_invited_rows_for_unified_document(self.ud_id)), 1)
