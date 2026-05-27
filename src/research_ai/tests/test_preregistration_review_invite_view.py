from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from hub.models import Hub
from hub.tests.helpers import create_hub
from purchase.models import Grant, GrantApplication
from research_ai.models import Expert, ExpertSearch, GeneratedEmail, SearchExpert
from researchhub_access_group.constants import ASSOCIATE_EDITOR
from researchhub_access_group.models import Permission
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from user.tests.helpers import create_random_authenticated_user


def _make_grant(*, created_by, contacts=None):
    post = create_post(created_by=created_by, document_type=GRANT)
    grant = Grant.objects.create(
        created_by=created_by,
        unified_document=post.unified_document,
        amount=Decimal("50000.00"),
        currency="USD",
        organization="National Science Foundation",
        short_title="AI Healthcare RFP",
        description="Research grant for AI applications in healthcare",
        status=Grant.OPEN,
        end_date=timezone.now() + timedelta(days=30),
    )
    if contacts:
        grant.contacts.set(contacts)
    return grant


def _make_preregistration(*, created_by, title="Novel AI Treatment Proposal"):
    return create_post(
        title=title,
        created_by=created_by,
        document_type=PREREGISTRATION,
    )


def _make_application(*, grant, preregistration_post, applicant):
    return GrantApplication.objects.create(
        grant=grant,
        preregistration_post=preregistration_post,
        applicant=applicant,
    )


def _make_hub_editor():
    user = create_random_authenticated_user("editor", moderator=False)
    hub = create_hub("editor-hub")
    Permission.objects.create(
        access_type=ASSOCIATE_EDITOR,
        content_type=ContentType.objects.get_for_model(Hub),
        object_id=hub.id,
        user=user,
    )
    Token.objects.get_or_create(user=user)
    return user


class InvitePreregistrationReviewersViewTests(APITestCase):
    def setUp(self):
        self.creator = create_random_authenticated_user("creator", moderator=False)
        self.contact = create_random_authenticated_user("contact", moderator=False)
        self.other = create_random_authenticated_user("other", moderator=False)
        self.moderator = create_random_authenticated_user("mod", moderator=True)
        self.applicant = create_random_authenticated_user("applicant", moderator=False)
        self.grant = _make_grant(created_by=self.creator, contacts=[self.contact])
        self.preregistration = _make_preregistration(created_by=self.applicant)
        self.application = _make_application(
            grant=self.grant,
            preregistration_post=self.preregistration,
            applicant=self.applicant,
        )
        self.url = (
            f"/api/research_ai/expert-finder/grant/{self.grant.id}/"
            f"preregistration/{self.preregistration.id}/invite-reviewers/"
        )

    def _post(self, body=None):
        return self.client.post(
            self.url, body or {"emails": ["a@example.com"]}, format="json"
        )

    def test_requires_authentication(self):
        self.assertEqual(self._post().status_code, status.HTTP_401_UNAUTHORIZED)

    def test_rejects_unrelated_user(self):
        self.client.force_authenticate(self.other)
        self.assertEqual(self._post().status_code, status.HTTP_403_FORBIDDEN)

    def test_returns_404_for_missing_grant(self):
        self.client.force_authenticate(self.creator)
        url = (
            f"/api/research_ai/expert-finder/grant/999999/"
            f"preregistration/{self.preregistration.id}/invite-reviewers/"
        )
        resp = self.client.post(url, {"emails": ["a@example.com"]}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_returns_404_for_missing_preregistration(self):
        self.client.force_authenticate(self.creator)
        url = (
            f"/api/research_ai/expert-finder/grant/{self.grant.id}/"
            f"preregistration/999999/invite-reviewers/"
        )
        resp = self.client.post(url, {"emails": ["a@example.com"]}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_returns_404_for_unapplied_preregistration(self):
        self.client.force_authenticate(self.creator)
        unrelated_post = _make_preregistration(
            created_by=self.applicant, title="Unrelated proposal"
        )
        url = (
            f"/api/research_ai/expert-finder/grant/{self.grant.id}/"
            f"preregistration/{unrelated_post.id}/invite-reviewers/"
        )
        resp = self.client.post(url, {"emails": ["a@example.com"]}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_returns_404_for_non_preregistration_post(self):
        self.client.force_authenticate(self.creator)
        non_prereg = create_post(created_by=self.applicant, document_type="DISCUSSION")
        url = (
            f"/api/research_ai/expert-finder/grant/{self.grant.id}/"
            f"preregistration/{non_prereg.id}/invite-reviewers/"
        )
        resp = self.client.post(url, {"emails": ["a@example.com"]}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_emails_payload_required(self):
        self.client.force_authenticate(self.creator)
        resp = self.client.post(self.url, {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_email_returns_400(self):
        self.client.force_authenticate(self.creator)
        resp = self.client.post(self.url, {"emails": ["nope"]}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("research_ai.views.email_views.send_queued_emails_task.delay")
    def test_creator_can_invite_and_queues_send(self, mock_delay):
        self.client.force_authenticate(self.creator)
        resp = self._post(
            {"emails": ["jane@example.com", "JOHN@example.com", "jane@example.com"]}
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        data = resp.json()
        self.assertEqual(data["queued"], 2)
        self.assertEqual(data["skipped_existing"], [])
        self.assertEqual(len(data["generated_email_ids"]), 2)

        emails = GeneratedEmail.objects.order_by("id")
        self.assertEqual(emails.count(), 2)
        self.assertEqual(
            set(emails.values_list("expert_email", flat=True)),
            {"jane@example.com", "john@example.com"},
        )
        for ge in emails:
            self.assertEqual(ge.status, GeneratedEmail.Status.SENDING)
            self.assertIn(self.preregistration.title, ge.email_subject)
            self.assertEqual(ge.created_by, self.creator)
            self.assertIsNotNone(ge.expert_search_id)
            self.assertEqual(
                ge.expert_search.unified_document_id,
                self.preregistration.unified_document_id,
            )

        self.assertEqual(Expert.objects.count(), 2)
        self.assertEqual(SearchExpert.objects.count(), 2)
        search = ExpertSearch.objects.get()
        self.assertEqual(search.created_by, self.creator)
        self.assertEqual(
            search.unified_document_id, self.preregistration.unified_document_id
        )

        mock_delay.assert_called_once()
        kwargs = mock_delay.call_args.kwargs
        self.assertEqual(
            sorted(kwargs["generated_email_ids"]),
            sorted(data["generated_email_ids"]),
        )

    @patch("research_ai.views.email_views.send_queued_emails_task.delay")
    def test_grant_contact_can_invite(self, mock_delay):
        self.client.force_authenticate(self.contact)
        resp = self._post()
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(resp.json()["queued"], 1)
        mock_delay.assert_called_once()

    @patch("research_ai.views.email_views.send_queued_emails_task.delay")
    def test_moderator_can_invite(self, mock_delay):
        self.client.force_authenticate(self.moderator)
        resp = self._post()
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(resp.json()["queued"], 1)
        mock_delay.assert_called_once()

    @patch("research_ai.views.email_views.send_queued_emails_task.delay")
    def test_hub_editor_can_invite(self, mock_delay):
        editor = _make_hub_editor()
        self.client.force_authenticate(editor)
        resp = self._post()
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(resp.json()["queued"], 1)
        mock_delay.assert_called_once()

    @patch("research_ai.views.email_views.send_queued_emails_task.delay")
    def test_skips_already_invited_emails(self, mock_delay):
        self.client.force_authenticate(self.creator)
        first = self._post({"emails": ["dup@example.com"]})
        self.assertEqual(first.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(first.json()["queued"], 1)

        second = self._post({"emails": ["dup@example.com", "new@example.com"]})
        self.assertEqual(second.status_code, status.HTTP_202_ACCEPTED)
        body = second.json()
        self.assertEqual(body["queued"], 1)
        self.assertEqual(body["skipped_existing"], ["dup@example.com"])
        self.assertEqual(GeneratedEmail.objects.count(), 2)

        self.assertEqual(mock_delay.call_count, 2)

    @patch("research_ai.views.email_views.send_queued_emails_task.delay")
    def test_no_send_when_all_skipped(self, mock_delay):
        self.client.force_authenticate(self.creator)
        self.assertEqual(self._post().status_code, status.HTTP_202_ACCEPTED)
        mock_delay.reset_mock()
        resp = self._post()
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(resp.json()["queued"], 0)
        mock_delay.assert_not_called()

    @patch("research_ai.views.email_views.send_queued_emails_task.delay")
    def test_rejects_non_open_grant(self, mock_delay):
        for blocked_status in (
            Grant.PENDING,
            Grant.CLOSED,
            Grant.COMPLETED,
            Grant.DECLINED,
        ):
            with self.subTest(status=blocked_status):
                self.grant.status = blocked_status
                self.grant.save(update_fields=["status"])
                self.client.force_authenticate(self.creator)
                resp = self._post()
                self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(GeneratedEmail.objects.count(), 0)
                mock_delay.assert_not_called()
