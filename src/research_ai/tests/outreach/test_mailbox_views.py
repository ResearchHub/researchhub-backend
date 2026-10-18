from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APITestCase

from research_ai.models import OutreachMailbox
from research_ai.services.outreach.instantly_client import InstantlyAPIError
from research_ai.services.outreach.mailbox_service import (
    MailboxAlreadyConnectedError,
    MailboxNotFoundError,
    MailboxOAuthSessionNotFoundError,
    MailboxOwnedByOtherEditorError,
)
from user.tests.helpers import create_random_authenticated_user


class OutreachMailboxListCreateViewTests(APITestCase):
    def setUp(self):
        self.editor = create_random_authenticated_user("om_list_v", moderator=True)
        self.url = "/api/research_ai/expert-finder/outreach-mailboxes/"

    def test_list_returns_editor_mailboxes_only(self):
        # Arrange
        mine = OutreachMailbox.objects.create(
            editor=self.editor,
            email="mine@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
            daily_limit=30,
        )
        other = create_random_authenticated_user("om_other_v", moderator=True)
        OutreachMailbox.objects.create(
            editor=other,
            email="other@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
        )
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(len(body["mailboxes"]), 1)
        row = body["mailboxes"][0]
        self.assertEqual(row["id"], mine.id)
        self.assertEqual(row["email"], "mine@gmail.com")
        self.assertEqual(row["status"], OutreachMailbox.Status.ACTIVE)
        self.assertEqual(row["daily_limit"], 30)
        self.assertEqual(row["reply_to"], "")
        self.assertEqual(row["provider_code"], 1)
        self.assertIn("created_date", row)
        self.assertIn("updated_date", row)
        self.assertNotIn("app_password", row)
        self.assertNotIn("password", row)

    @patch("research_ai.views.template_views.OutreachMailboxService")
    def test_connect_returns_created_mailbox_without_password(self, mock_service_cls):
        # Arrange
        mailbox = OutreachMailbox.objects.create(
            editor=self.editor,
            email="new@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
            daily_limit=30,
        )
        service = mock_service_cls.return_value
        service.connect_mailbox.return_value = mailbox
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.post(
            self.url,
            {"email": "new@gmail.com", "app_password": "secret-app-password"},
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        body = response.json()
        self.assertEqual(body["id"], mailbox.id)
        self.assertEqual(body["email"], "new@gmail.com")
        self.assertNotIn("app_password", body)
        self.assertNotIn("password", body)
        service.connect_mailbox.assert_called_once_with(
            self.editor,
            email="new@gmail.com",
            app_password="secret-app-password",
            reply_to=None,
        )

    @patch("research_ai.views.template_views.OutreachMailboxService")
    def test_connect_passes_optional_reply_to(self, mock_service_cls):
        # Arrange
        mailbox = OutreachMailbox.objects.create(
            editor=self.editor,
            email="new@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
            daily_limit=30,
            reply_to="replies@researchhub.com",
        )
        service = mock_service_cls.return_value
        service.connect_mailbox.return_value = mailbox
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.post(
            self.url,
            {
                "email": "new@gmail.com",
                "app_password": "secret-app-password",
                "reply_to": "replies@researchhub.com",
            },
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["reply_to"], "replies@researchhub.com")
        service.connect_mailbox.assert_called_once_with(
            self.editor,
            email="new@gmail.com",
            app_password="secret-app-password",
            reply_to="replies@researchhub.com",
        )

    @patch("research_ai.views.template_views.OutreachMailboxService")
    def test_connect_conflict_when_already_connected(self, mock_service_cls):
        # Arrange
        service = mock_service_cls.return_value
        service.connect_mailbox.side_effect = MailboxAlreadyConnectedError(
            "This Gmail address is already connected."
        )
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.post(
            self.url,
            {"email": "dup@gmail.com", "app_password": "secret"},
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        body = response.json()
        msg = "This Gmail address is already connected."
        self.assertEqual(body["detail"], msg)
        self.assertEqual(body["error"], "already_connected")
        self.assertEqual(body["error_description"], msg)
        self.assertEqual(body["status"], "error")

    @patch("research_ai.views.template_views.OutreachMailboxService")
    def test_connect_conflict_when_owned_by_other_editor(self, mock_service_cls):
        # Arrange
        service = mock_service_cls.return_value
        service.connect_mailbox.side_effect = MailboxOwnedByOtherEditorError(
            "This Gmail address is already connected by another editor."
        )
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.post(
            self.url,
            {"email": "taken@gmail.com", "app_password": "secret"},
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        body = response.json()
        msg = "This Gmail address is already connected by another editor."
        self.assertEqual(body["detail"], msg)
        self.assertEqual(body["error"], "owned_by_other")
        self.assertEqual(body["error_description"], msg)
        self.assertEqual(body["status"], "error")

    def test_connect_requires_app_password(self):
        # Arrange
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.post(
            self.url,
            {"email": "missing-pw@gmail.com"},
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class OutreachMailboxDetailViewTests(APITestCase):
    def setUp(self):
        self.editor = create_random_authenticated_user("om_del_v", moderator=True)
        self.mailbox = OutreachMailbox.objects.create(
            editor=self.editor,
            email="detach@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
            daily_limit=30,
        )
        self.url = (
            f"/api/research_ai/expert-finder/outreach-mailboxes/{self.mailbox.id}/"
        )

    @patch("research_ai.views.template_views.OutreachMailboxService")
    def test_detach_returns_204(self, mock_service_cls):
        # Arrange
        service = mock_service_cls.return_value
        service.detach_mailbox.return_value = self.mailbox
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.delete(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        service.detach_mailbox.assert_called_once_with(self.editor, self.mailbox.id)

    @patch("research_ai.views.template_views.OutreachMailboxService")
    def test_detach_not_found(self, mock_service_cls):
        # Arrange
        service = mock_service_cls.return_value
        service.detach_mailbox.side_effect = MailboxNotFoundError(
            "Outreach mailbox not found."
        )
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.delete(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("research_ai.views.template_views.OutreachMailboxService")
    def test_detach_instantly_error_returns_502(self, mock_service_cls):
        # Arrange
        service = mock_service_cls.return_value
        service.detach_mailbox.side_effect = InstantlyAPIError("upstream failed")
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.delete(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)

    @patch("research_ai.views.template_views.OutreachMailboxService")
    def test_patch_daily_limit_as_moderator(self, mock_service_cls):
        # Arrange
        self.mailbox.daily_limit = 50
        self.mailbox.save(update_fields=["daily_limit"])
        service = mock_service_cls.return_value
        service.update_mailbox.return_value = self.mailbox
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.patch(self.url, {"daily_limit": 50}, format="json")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["daily_limit"], 50)
        service.update_mailbox.assert_called_once_with(
            self.editor, self.mailbox.id, daily_limit=50
        )

    @patch("research_ai.views.template_views.OutreachMailboxService")
    def test_patch_reply_to(self, mock_service_cls):
        # Arrange
        self.mailbox.reply_to = "replies@researchhub.com"
        self.mailbox.save(update_fields=["reply_to"])
        service = mock_service_cls.return_value
        service.update_mailbox.return_value = self.mailbox
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.patch(
            self.url, {"reply_to": "replies@researchhub.com"}, format="json"
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["reply_to"], "replies@researchhub.com")
        service.update_mailbox.assert_called_once_with(
            self.editor,
            self.mailbox.id,
            reply_to="replies@researchhub.com",
        )

    def test_patch_daily_limit_validates_body(self):
        # Arrange
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.patch(self.url, {"daily_limit": 0}, format="json")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_requires_at_least_one_field(self):
        # Arrange
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.patch(self.url, {}, format="json")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class OutreachCapacityViewTests(APITestCase):
    def setUp(self):
        self.editor = create_random_authenticated_user("om_cap_v", moderator=True)
        self.url = "/api/research_ai/expert-finder/outreach-capacity/"

    @patch("research_ai.views.template_views.OutreachMailboxService")
    def test_capacity_summary_shape(self, mock_service_cls):
        # Arrange
        service = mock_service_cls.return_value
        service.get_capacity_summary.return_value = {
            "active_mailbox_count": 1,
            "daily_limit_total": 30,
            "sent_today": 10,
            "remaining_today": 20,
            "mailboxes": [
                {
                    "email": "a@gmail.com",
                    "status": OutreachMailbox.Status.ACTIVE,
                    "daily_limit": 30,
                    "sent_today": 10,
                    "remaining_today": 20,
                }
            ],
        }
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["active_mailbox_count"], 1)
        self.assertEqual(body["daily_limit_total"], 30)
        self.assertEqual(body["sent_today"], 10)
        self.assertEqual(body["remaining_today"], 20)
        self.assertEqual(len(body["mailboxes"]), 1)
        self.assertEqual(body["mailboxes"][0]["email"], "a@gmail.com")
        service.get_capacity_summary.assert_called_once_with(self.editor)


class OutreachMailboxOAuthInitViewTests(APITestCase):
    def setUp(self):
        self.editor = create_random_authenticated_user(
            "om_oauth_init_v", moderator=True
        )
        self.url = (
            "/api/research_ai/expert-finder/outreach-mailboxes/oauth/google/init/"
        )

    def test_init_requires_auth(self):
        # Act
        response = self.client.post(self.url, {}, format="json")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("research_ai.views.template_views.OutreachMailboxService")
    def test_google_init_returns_auth_url(self, mock_service_cls):
        # Arrange
        service = mock_service_cls.return_value
        service.start_oauth.return_value = {
            "session_id": "sess-1",
            "auth_url": "https://accounts.google.com/o/oauth2/v2/auth?x=1",
            "expires_at": "2024-01-15T10:30:00.000Z",
            "provider": "google",
        }
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.post(
            self.url,
            {"reply_to": "replies@researchhub.com"},
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["session_id"], "sess-1")
        self.assertEqual(
            body["auth_url"], "https://accounts.google.com/o/oauth2/v2/auth?x=1"
        )
        self.assertEqual(body["provider"], "google")
        service.start_oauth.assert_called_once_with(
            self.editor,
            reply_to="replies@researchhub.com",
        )

    @patch("research_ai.views.template_views.OutreachMailboxService")
    def test_init_maps_instantly_429(self, mock_service_cls):
        # Arrange
        service = mock_service_cls.return_value
        service.start_oauth.side_effect = InstantlyAPIError(
            "rate limited", status_code=429
        )
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.post(self.url, {}, format="json")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    @patch("research_ai.views.template_views.OutreachMailboxService")
    def test_init_maps_instantly_503_to_502(self, mock_service_cls):
        # Arrange
        service = mock_service_cls.return_value
        service.start_oauth.side_effect = InstantlyAPIError(
            "upstream unavailable", status_code=503
        )
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.post(self.url, {}, format="json")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)


class OutreachMailboxOAuthSessionViewTests(APITestCase):
    def setUp(self):
        self.editor = create_random_authenticated_user(
            "om_oauth_poll_v", moderator=True
        )
        self.session_id = "sess-view-1"
        self.url = (
            "/api/research_ai/expert-finder/outreach-mailboxes/"
            f"oauth/session/{self.session_id}/"
        )

    def test_poll_requires_auth(self):
        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("research_ai.views.template_views.OutreachMailboxService")
    def test_poll_success_includes_mailbox_json(self, mock_service_cls):
        # Arrange
        mailbox = OutreachMailbox.objects.create(
            editor=self.editor,
            email="editor@company.com",
            status=OutreachMailbox.Status.ACTIVE,
            daily_limit=40,
            provider_code=2,
            reply_to="replies@researchhub.com",
        )
        service = mock_service_cls.return_value
        service.poll_oauth.return_value = {
            "status": "success",
            "email": mailbox.email,
            "mailbox": mailbox,
        }
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["email"], "editor@company.com")
        self.assertEqual(body["mailbox"]["id"], mailbox.id)
        self.assertEqual(body["mailbox"]["email"], "editor@company.com")
        self.assertEqual(body["mailbox"]["provider_code"], 2)
        self.assertEqual(body["mailbox"]["reply_to"], "replies@researchhub.com")
        self.assertNotIn("app_password", body["mailbox"])
        service.poll_oauth.assert_called_once_with(self.editor, self.session_id)

    @patch("research_ai.views.template_views.OutreachMailboxService")
    def test_poll_pending(self, mock_service_cls):
        # Arrange
        service = mock_service_cls.return_value
        service.poll_oauth.return_value = {"status": "pending"}
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"status": "pending"})

    @patch("research_ai.views.template_views.OutreachMailboxService")
    def test_poll_session_not_found(self, mock_service_cls):
        # Arrange
        service = mock_service_cls.return_value
        service.poll_oauth.side_effect = MailboxOAuthSessionNotFoundError(
            "OAuth session not found."
        )
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("research_ai.views.template_views.OutreachMailboxService")
    def test_poll_ownership_conflict_returns_409(self, mock_service_cls):
        # Arrange
        service = mock_service_cls.return_value
        service.poll_oauth.side_effect = MailboxOwnedByOtherEditorError(
            "This email address is already connected by another editor."
        )
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        body = response.json()
        msg = "This email address is already connected by another editor."
        self.assertEqual(body["detail"], msg)
        self.assertEqual(body["error"], "owned_by_other")
        self.assertEqual(body["error_description"], msg)
        self.assertEqual(body["status"], "error")
