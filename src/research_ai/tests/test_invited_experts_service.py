from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from research_ai.models import Expert, ExpertSearch, GeneratedEmail, SearchExpert
from research_ai.services.invited_experts_service import get_document_invited_rows
from user.tests.helpers import create_user


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

    def test_registered_expert_on_search_appears_in_rows(self):
        anchor = timezone.now() - timedelta(days=2)
        search = ExpertSearch.objects.create(
            created_by=self.creator,
            unified_document_id=self.ud_id,
            query="Test",
            status=ExpertSearch.Status.COMPLETED,
            completed_at=anchor,
        )
        joiner = create_user(
            email="joiner@example.com",
            first_name="J",
            last_name="R",
        )
        from user.models import User

        User.objects.filter(pk=joiner.pk).update(date_joined=anchor + timedelta(days=1))
        expert = Expert.objects.create(
            email="joiner@example.com",
            first_name="J",
            last_name="R",
            registered_user=joiner,
        )
        SearchExpert.objects.create(
            expert_search=search, expert=expert, position=0
        )
        ge = GeneratedEmail.objects.create(
            created_by=self.creator,
            expert_search=search,
            expert_email="joiner@example.com",
        )
        rows, total = get_document_invited_rows(self.ud_id)
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["expert_search_id"], search.id)
        self.assertEqual(rows[0]["generated_email_id"], ge.id)
        self.assertEqual(rows[0]["user"].id, joiner.id)

    def test_registered_expert_without_generated_email_has_null_ge_id(self):
        search = ExpertSearch.objects.create(
            created_by=self.creator,
            unified_document_id=self.ud_id,
            query="Test",
            status=ExpertSearch.Status.COMPLETED,
        )
        joiner = create_user(email="nogeo@example.com", first_name="N", last_name="G")
        expert = Expert.objects.create(
            email="nogeo@example.com",
            registered_user=joiner,
        )
        SearchExpert.objects.create(
            expert_search=search, expert=expert, position=0
        )
        rows, total = get_document_invited_rows(self.ud_id)
        self.assertEqual(total, 1)
        self.assertIsNone(rows[0]["generated_email_id"])

    def test_expert_without_registered_user_excluded(self):
        search = ExpertSearch.objects.create(
            created_by=self.creator,
            unified_document_id=self.ud_id,
            query="Test",
            status=ExpertSearch.Status.COMPLETED,
        )
        expert = Expert.objects.create(
            email="anon@example.com",
            first_name="A",
            last_name="Non",
        )
        SearchExpert.objects.create(
            expert_search=search, expert=expert, position=0
        )
        rows, total = get_document_invited_rows(self.ud_id)
        self.assertEqual(total, 0)
        self.assertEqual(rows, [])


class LinkExpertOnUserCreatedSignalTests(TestCase):
    def test_new_user_links_expert_when_outreach_in_window(self):
        creator = create_user(email="ge_creator@sig.test")
        Expert.objects.create(email="signal@test.com", first_name="S")
        anchor = timezone.now() - timedelta(days=1)
        ge = GeneratedEmail.objects.create(
            created_by=creator,
            expert_email="signal@test.com",
            expert_name="S",
        )
        GeneratedEmail.objects.filter(pk=ge.pk).update(created_date=anchor)
        u = create_user(email="signal@test.com", first_name="U", last_name="X")
        ex = Expert.objects.get(email__iexact="signal@test.com")
        self.assertEqual(ex.registered_user_id, u.id)

    def test_new_user_does_not_link_without_generated_email(self):
        Expert.objects.create(email="orphan@example.com", first_name="O")
        create_user(email="orphan@example.com")
        ex = Expert.objects.get(email__iexact="orphan@example.com")
        self.assertIsNone(ex.registered_user_id)

    def test_new_user_does_not_link_when_outreach_outside_window(self):
        creator = create_user(email="c2@sig.test")
        Expert.objects.create(email="oldge@example.com", first_name="O")
        ge = GeneratedEmail.objects.create(
            created_by=creator,
            expert_email="oldge@example.com",
            expert_name="O",
        )
        GeneratedEmail.objects.filter(pk=ge.pk).update(
            created_date=timezone.now() - timedelta(days=10)
        )
        create_user(email="oldge@example.com")
        ex = Expert.objects.get(email__iexact="oldge@example.com")
        self.assertIsNone(ex.registered_user_id)

    def test_new_user_does_not_link_when_outreach_closed(self):
        creator = create_user(email="c3@sig.test")
        Expert.objects.create(email="closed@example.com", first_name="C")
        anchor = timezone.now() - timedelta(days=1)
        ge = GeneratedEmail.objects.create(
            created_by=creator,
            expert_email="closed@example.com",
            expert_name="C",
            status=GeneratedEmail.Status.CLOSED,
        )
        GeneratedEmail.objects.filter(pk=ge.pk).update(created_date=anchor)
        create_user(email="closed@example.com")
        ex = Expert.objects.get(email__iexact="closed@example.com")
        self.assertIsNone(ex.registered_user_id)
