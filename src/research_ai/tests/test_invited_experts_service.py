from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from research_ai.models import Expert, ExpertSearch, GeneratedEmail
from research_ai.services.invited_experts_service import (
    get_document_invited_rows,
    get_document_invite_candidates_for_email,
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
            expert_results=[],
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
            expert_results=[],
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
            expert_results=[],
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
            expert_results=[],
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
            expert_results=[],
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


class GetDocumentInvitedRowsTests(TestCase):
    def setUp(self):
        from paper.tests.helpers import create_paper

        self.creator = create_user(email="creator@rows.test")
        self.paper = create_paper(
            title="Rows doc",
            paper_publish_date="2021-01-01",
        )
        self.ud_id = self.paper.unified_document_id

    def test_no_users_returns_empty(self):
        rows, total = get_document_invited_rows(self.ud_id)
        self.assertEqual(total, 0)
        self.assertEqual(rows, [])

    def test_user_in_window_appears_in_rows(self):
        anchor = timezone.now() - timedelta(days=2)
        search = ExpertSearch.objects.create(
            created_by=self.creator,
            unified_document_id=self.ud_id,
            query="Test",
            status=ExpertSearch.Status.COMPLETED,
            completed_at=anchor,
            expert_results=[],
        )
        ge = GeneratedEmail.objects.create(
            created_by=self.creator,
            expert_search=search,
            expert_email="joiner@example.com",
        )
        # DefaultModel.created_date uses auto_now_add; set explicitly for window math.
        GeneratedEmail.objects.filter(pk=ge.pk).update(created_date=anchor)
        ge.refresh_from_db()
        joiner = create_user(
            email="joiner@example.com",
            first_name="J",
            last_name="R",
        )
        from user.models import User

        User.objects.filter(pk=joiner.pk).update(
            date_joined=anchor + timedelta(days=1)
        )
        rows, total = get_document_invited_rows(self.ud_id)
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["expert_search_id"], search.id)
        self.assertEqual(rows[0]["generated_email_id"], ge.id)
        self.assertEqual(rows[0]["user"].id, joiner.id)


class LinkExpertOnUserCreatedSignalTests(TestCase):
    def test_new_user_sets_registered_user_on_matching_expert(self):
        Expert.objects.create(email="signal@test.com", first_name="S")
        u = create_user(email="signal@test.com", first_name="U", last_name="X")
        ex = Expert.objects.get(email__iexact="signal@test.com")
        self.assertEqual(ex.registered_user_id, u.id)
