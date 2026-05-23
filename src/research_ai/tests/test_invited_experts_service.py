from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.utils import timezone

from paper.tests.helpers import create_paper
from research_ai.models import Expert, ExpertSearch, GeneratedEmail, SearchExpert
from research_ai.services.invited_experts_service import (
    grant_invited_expert_access_for_send,
    grant_invited_expert_access_for_signup,
)
from researchhub_access_group.constants import VIEWER
from researchhub_access_group.models import Permission
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_user


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class InvitedExpertsSignalTests(TestCase):
    """Signup links ``Expert.registered_user`` when outreach qualifies."""

    def setUp(self):
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
        create_user(
            email="late@example.com",
            first_name="Late",
            last_name="User",
        )
        ex.refresh_from_db()
        self.assertIsNone(ex.registered_user_id)

    def test_user_created_email_not_in_any_search_does_not_link(self):
        stranger = create_user(
            email="stranger@example.com",
            first_name="Stranger",
            last_name="User",
        )
        self.assertFalse(Expert.objects.filter(registered_user_id=stranger.id).exists())

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


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class GrantInvitedExpertAccessTests(TestCase):
    """Signup grants VIEWER permission on private preregistrations the user was
    invited to via a sent expert-finder outreach email."""

    def setUp(self):
        self.creator = create_user(email="creator@invited.test")
        self.unified_doc_ct = ContentType.objects.get_for_model(
            ResearchhubUnifiedDocument
        )

    def _make_private_preregistration(self):
        post = create_post(
            title="Private prereg",
            created_by=self.creator,
            document_type=PREREGISTRATION,
        )
        post.unified_document.is_public = False
        post.unified_document.save(update_fields=["is_public"])
        return post

    def _make_search(self, unified_document, completed_at):
        return ExpertSearch.objects.create(
            created_by=self.creator,
            unified_document=unified_document,
            query="Test",
            status=ExpertSearch.Status.COMPLETED,
            completed_at=completed_at,
        )

    def _make_generated_email(
        self,
        *,
        search,
        email,
        status=GeneratedEmail.Status.SENT,
        created_at=None,
    ):
        ge = GeneratedEmail.objects.create(
            created_by=self.creator,
            expert_search=search,
            expert_email=email,
            status=status,
        )
        if created_at is not None:
            GeneratedEmail.objects.filter(pk=ge.pk).update(created_date=created_at)
        return ge

    def test_sent_email_in_window_grants_viewer_permission(self):
        when = timezone.now() - timedelta(days=2)
        post = self._make_private_preregistration()
        search = self._make_search(post.unified_document, when)
        self._make_generated_email(
            search=search, email="invitee@example.com", created_at=when
        )

        new_user = create_user(
            email="invitee@example.com", first_name="In", last_name="Vitee"
        )

        perm = Permission.objects.get(
            content_type=self.unified_doc_ct,
            object_id=post.unified_document_id,
            user=new_user,
        )
        self.assertEqual(perm.access_type, VIEWER)

    def test_draft_email_does_not_grant_permission(self):
        when = timezone.now() - timedelta(days=1)
        post = self._make_private_preregistration()
        search = self._make_search(post.unified_document, when)
        self._make_generated_email(
            search=search,
            email="draftonly@example.com",
            status=GeneratedEmail.Status.DRAFT,
            created_at=when,
        )

        new_user = create_user(
            email="draftonly@example.com", first_name="D", last_name="Raft"
        )

        self.assertFalse(
            Permission.objects.filter(
                content_type=self.unified_doc_ct,
                object_id=post.unified_document_id,
                user=new_user,
            ).exists()
        )

    def test_sent_email_outside_window_does_not_grant_permission(self):
        when = timezone.now() - timedelta(days=10)
        post = self._make_private_preregistration()
        search = self._make_search(post.unified_document, when)
        self._make_generated_email(
            search=search, email="late@example.com", created_at=when
        )

        new_user = create_user(
            email="late@example.com", first_name="La", last_name="Te"
        )

        self.assertFalse(
            Permission.objects.filter(
                content_type=self.unified_doc_ct,
                object_id=post.unified_document_id,
                user=new_user,
            ).exists()
        )

    def test_public_document_does_not_grant_permission(self):
        when = timezone.now() - timedelta(days=2)
        public_post = create_post(
            title="Public prereg",
            created_by=self.creator,
            document_type=PREREGISTRATION,
        )
        # default is_public=True
        search = self._make_search(public_post.unified_document, when)
        self._make_generated_email(
            search=search, email="onpublic@example.com", created_at=when
        )

        new_user = create_user(
            email="onpublic@example.com", first_name="O", last_name="Pub"
        )

        self.assertFalse(
            Permission.objects.filter(
                content_type=self.unified_doc_ct,
                object_id=public_post.unified_document_id,
                user=new_user,
            ).exists()
        )

    def test_non_preregistration_document_does_not_grant_permission(self):
        when = timezone.now() - timedelta(days=2)
        post = create_post(
            title="Private discussion",
            created_by=self.creator,
            document_type=DISCUSSION,
        )
        post.unified_document.is_public = False
        post.unified_document.save(update_fields=["is_public"])

        search = self._make_search(post.unified_document, when)
        self._make_generated_email(
            search=search, email="notprereg@example.com", created_at=when
        )

        new_user = create_user(
            email="notprereg@example.com", first_name="N", last_name="P"
        )

        self.assertFalse(
            Permission.objects.filter(
                content_type=self.unified_doc_ct,
                object_id=post.unified_document_id,
                user=new_user,
            ).exists()
        )

    def test_grant_is_idempotent(self):
        when = timezone.now() - timedelta(days=2)
        post = self._make_private_preregistration()
        search = self._make_search(post.unified_document, when)
        self._make_generated_email(
            search=search, email="dupe@example.com", created_at=when
        )

        new_user = create_user(
            email="dupe@example.com", first_name="D", last_name="Upe"
        )

        # Re-run the granter; should not create a second Permission row.
        grant_invited_expert_access_for_signup(
            normalized_email="dupe@example.com", user=new_user
        )
        self.assertEqual(
            Permission.objects.filter(
                content_type=self.unified_doc_ct,
                object_id=post.unified_document_id,
                user=new_user,
            ).count(),
            1,
        )


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class GrantInvitedExpertAccessOnSendTests(TestCase):
    """Send-time grant covers experts who are *already* users at invite time."""

    def setUp(self):
        self.creator = create_user(email="creator@send.test")
        self.unified_doc_ct = ContentType.objects.get_for_model(
            ResearchhubUnifiedDocument
        )

    def _make_private_preregistration(self):
        post = create_post(
            title="Private prereg send",
            created_by=self.creator,
            document_type=PREREGISTRATION,
        )
        post.unified_document.is_public = False
        post.unified_document.save(update_fields=["is_public"])
        return post

    def _make_search(self, unified_document):
        return ExpertSearch.objects.create(
            created_by=self.creator,
            unified_document=unified_document,
            query="Test",
            status=ExpertSearch.Status.COMPLETED,
        )

    def _make_generated_email(self, *, search, email):
        return GeneratedEmail.objects.create(
            created_by=self.creator,
            expert_search=search,
            expert_email=email,
            status=GeneratedEmail.Status.SENDING,
        )

    def test_grants_viewer_when_expert_linked_to_user(self):
        existing_user = create_user(email="already@example.com")
        post = self._make_private_preregistration()
        search = self._make_search(post.unified_document)
        Expert.objects.create(
            email="already@example.com",
            registered_user=existing_user,
        )
        ge = self._make_generated_email(search=search, email="already@example.com")

        created = grant_invited_expert_access_for_send(generated_email=ge)

        self.assertTrue(created)
        perm = Permission.objects.get(
            content_type=self.unified_doc_ct,
            object_id=post.unified_document_id,
            user=existing_user,
        )
        self.assertEqual(perm.access_type, VIEWER)

    def test_no_grant_when_expert_has_no_registered_user(self):
        post = self._make_private_preregistration()
        search = self._make_search(post.unified_document)
        Expert.objects.create(email="cold@example.com")
        ge = self._make_generated_email(search=search, email="cold@example.com")

        self.assertFalse(grant_invited_expert_access_for_send(generated_email=ge))
        self.assertFalse(
            Permission.objects.filter(
                content_type=self.unified_doc_ct,
                object_id=post.unified_document_id,
            ).exists()
        )

    def test_no_grant_for_public_document(self):
        existing_user = create_user(email="pub@example.com")
        public_post = create_post(
            title="Public prereg",
            created_by=self.creator,
            document_type=PREREGISTRATION,
        )
        # default is_public=True
        search = self._make_search(public_post.unified_document)
        Expert.objects.create(
            email="pub@example.com",
            registered_user=existing_user,
        )
        ge = self._make_generated_email(search=search, email="pub@example.com")

        self.assertFalse(grant_invited_expert_access_for_send(generated_email=ge))

    def test_no_grant_for_non_preregistration(self):
        existing_user = create_user(email="discuss@example.com")
        post = create_post(
            title="Discussion",
            created_by=self.creator,
            document_type=DISCUSSION,
        )
        post.unified_document.is_public = False
        post.unified_document.save(update_fields=["is_public"])
        search = self._make_search(post.unified_document)
        Expert.objects.create(
            email="discuss@example.com",
            registered_user=existing_user,
        )
        ge = self._make_generated_email(search=search, email="discuss@example.com")

        self.assertFalse(grant_invited_expert_access_for_send(generated_email=ge))

    def test_idempotent(self):
        existing_user = create_user(email="twice@example.com")
        post = self._make_private_preregistration()
        search = self._make_search(post.unified_document)
        Expert.objects.create(
            email="twice@example.com",
            registered_user=existing_user,
        )
        ge = self._make_generated_email(search=search, email="twice@example.com")

        self.assertTrue(grant_invited_expert_access_for_send(generated_email=ge))
        # Second call: existing Permission, no new row.
        self.assertFalse(grant_invited_expert_access_for_send(generated_email=ge))
        self.assertEqual(
            Permission.objects.filter(
                content_type=self.unified_doc_ct,
                object_id=post.unified_document_id,
                user=existing_user,
            ).count(),
            1,
        )

    def test_no_search_attached_returns_false(self):
        existing_user = create_user(email="orphan@example.com")
        Expert.objects.create(
            email="orphan@example.com",
            registered_user=existing_user,
        )
        ge = GeneratedEmail.objects.create(
            created_by=self.creator,
            expert_search=None,
            expert_email="orphan@example.com",
            status=GeneratedEmail.Status.SENDING,
        )

        self.assertFalse(grant_invited_expert_access_for_send(generated_email=ge))
