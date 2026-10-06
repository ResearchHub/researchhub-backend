from datetime import timedelta
from unittest.mock import patch

from botocore.exceptions import ClientError
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from research_ai.models import AgentConversation, AgentFile
from research_ai.services.agent_persistence import AgentConversationService
from research_ai.tests.agent_files.helpers import make_file
from research_ai.throttles import AgentFileCreateThrottle
from utils.test_helpers import AWSMockMixin

FILES_URL = "/api/research_ai/files/"
CHATS_URL = "/api/research_ai/assistant/chats/"
BUCKET = "researchhub-test-private-storage"
MODEL_SETTINGS = {
    "ANTHROPIC_AWS_WORKSPACE_ID": "ws-test",
    "AWS_REGION_NAME": "us-east-1",
    "OPENROUTER_API_KEY": "or-test",
}


@override_settings(AWS_PRIVATE_STORAGE_BUCKET_NAME=BUCKET, **MODEL_SETTINGS)
class AgentFileViewTests(AWSMockMixin, APITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            username="owner@researchhub_test.com",
            password="password",
            email="owner@researchhub_test.com",
        )
        self.other = user_model.objects.create_user(
            username="other@researchhub_test.com",
            password="password",
            email="other@researchhub_test.com",
        )
        self.mock_aws_client.generate_presigned_post.return_value = {
            "url": f"https://{BUCKET}.s3.amazonaws.com/",
            "fields": {"key": "uploads/k", "policy": "p", "Content-Type": "x"},
        }
        self.client.force_authenticate(self.owner)

    def _file_url(self, file_id, suffix=""):
        return f"{FILES_URL}{file_id}/{suffix}"

    def test_requires_authentication(self):
        # Arrange
        self.client.force_authenticate(None)

        # Act
        response = self.client.post(
            FILES_URL, {"filename": "a.pdf", "size_bytes": 1}, format="json"
        )

        # Assert
        self.assertEqual(response.status_code, 401)

    def test_a_blocked_user_is_refused(self):
        # Arrange
        self.owner.probable_spammer = True
        self.owner.save(update_fields=["probable_spammer"])
        file = make_file(self.owner)

        for method, url in (
            ("post", FILES_URL),
            ("get", self._file_url(file.id)),
            ("delete", self._file_url(file.id)),
            ("post", self._file_url(file.id, "complete/")),
            ("get", self._file_url(file.id, "download/")),
        ):
            with self.subTest(method=method, url=url):
                # Act
                response = getattr(self.client, method)(
                    url, {"filename": "a.pdf", "size_bytes": 1}
                )

                # Assert
                self.assertEqual(response.status_code, 403)

    def test_upload_flow_from_form_to_processing(self):
        # Act: start the upload, then confirm it after the browser posts it.
        created = self.client.post(
            FILES_URL,
            {"filename": "Aims.pdf", "size_bytes": 2048, "content_type": "x/y"},
            format="json",
        )
        self.mock_aws_client.head_object.return_value = {
            "ContentLength": 2048,
            "ContentType": "application/pdf",
        }
        with (
            patch("research_ai.tasks.process_agent_file_task.delay") as delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            completed = self.client.post(
                self._file_url(created.data["id"], "complete/")
            )
        polled = self.client.get(self._file_url(created.data["id"]))

        # Assert
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data["status"], AgentFile.Status.UPLOADING)
        self.assertEqual(created.data["content_type"], "application/pdf")
        self.assertEqual(
            created.data["upload"]["url"], f"https://{BUCKET}.s3.amazonaws.com/"
        )
        self.assertEqual(created.data["upload"]["fields"]["policy"], "p")
        _args, kwargs = self.mock_aws_client.generate_presigned_post.call_args
        self.assertEqual(kwargs["Bucket"], BUCKET)
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.data["status"], AgentFile.Status.PROCESSING)
        delay.assert_called_once_with(created.data["id"])
        self.assertEqual(polled.data["status"], AgentFile.Status.PROCESSING)

    def test_create_explains_an_unsupported_file(self):
        # Act
        response = self.client.post(
            FILES_URL, {"filename": "deck.pptx", "size_bytes": 10}, format="json"
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "unsupported_file_type")

    def test_create_refuses_a_file_over_the_size_limit(self):
        # Act
        response = self.client.post(
            FILES_URL,
            {"filename": "big.pdf", "size_bytes": 26 * 1024 * 1024},
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "file_too_large")
        self.assertIn("25 MB", response.data["detail"])

    @override_settings(RESEARCH_AI_FILE_MAX_UNSENT=1)
    def test_create_refuses_more_unsent_files_than_the_cap(self):
        # Arrange
        make_file(self.owner)

        # Act
        response = self.client.post(
            FILES_URL, {"filename": "a.pdf", "size_bytes": 10}, format="json"
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "too_many_unsent_files")

    def test_create_is_rate_limited_per_user(self):
        # Arrange
        payload = {"filename": "a.pdf", "size_bytes": 10}

        # Act
        with patch.object(AgentFileCreateThrottle, "rate", "2/hour"):
            statuses = [
                self.client.post(FILES_URL, payload, format="json").status_code
                for _ in range(3)
            ]
            self.client.force_authenticate(self.other)
            other = self.client.post(FILES_URL, payload, format="json")

        # Assert
        self.assertEqual(statuses, [201, 201, 429])
        self.assertEqual(other.status_code, 201)

    @override_settings(AWS_PRIVATE_STORAGE_BUCKET_NAME="")
    def test_create_is_unavailable_without_the_private_bucket(self):
        # Act
        response = self.client.post(
            FILES_URL, {"filename": "a.pdf", "size_bytes": 10}, format="json"
        )

        # Assert
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], "uploads_unavailable")

    def test_complete_before_the_object_lands_is_a_conflict(self):
        # Arrange
        file = make_file(self.owner, status=AgentFile.Status.UPLOADING)
        self.mock_aws_client.head_object.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "HeadObject"
        )

        # Act
        response = self.client.post(self._file_url(file.id, "complete/"))

        # Assert
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "upload_incomplete")

    def test_polling_fails_a_file_whose_processing_stalled(self):
        # Arrange
        file = make_file(
            self.owner,
            status=AgentFile.Status.PROCESSING,
            processing_started_date=timezone.now() - timedelta(hours=1),
        )

        # Act
        response = self.client.get(self._file_url(file.id))

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], AgentFile.Status.FAILED)
        self.assertIn("took too long", response.data["error"])
        self.mock_aws_client.delete_object.assert_called_once_with(
            Bucket=BUCKET, Key=file.storage_key
        )

    def test_files_are_private_to_their_uploader(self):
        # Arrange
        file = make_file(self.other)

        for method, suffix in (
            ("get", ""),
            ("delete", ""),
            ("post", "complete/"),
            ("get", "download/"),
        ):
            with self.subTest(method=method, suffix=suffix):
                # Act
                response = getattr(self.client, method)(self._file_url(file.id, suffix))

                # Assert
                self.assertEqual(response.status_code, 404)
        self.assertTrue(AgentFile.objects.filter(id=file.id).exists())

    def test_delete_removes_an_unsent_file_but_not_a_sent_one(self):
        # Arrange
        unsent = make_file(self.owner)
        chat_id = self.client.post(CHATS_URL, {}, format="json").data["conversation_id"]
        message = AgentConversationService().add_human_message(
            AgentConversation.objects.get(id=chat_id), "hi"
        )
        sent = make_file(self.owner, message=message)

        # Act
        removed = self.client.delete(self._file_url(unsent.id))
        refused = self.client.delete(self._file_url(sent.id))

        # Assert
        self.assertEqual(removed.status_code, 204)
        self.assertEqual(self.client.get(self._file_url(unsent.id)).status_code, 404)
        self.mock_aws_client.delete_object.assert_called_once_with(
            Bucket=BUCKET, Key=unsent.storage_key
        )
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.data["code"], "attachment_sent")

    def test_download_returns_a_short_lived_url(self):
        # Arrange
        file = make_file(self.owner, etag='"v1"')
        self.mock_aws_client.head_object.return_value = {
            "ContentLength": 100,
            "ContentType": "application/pdf",
            "ETag": '"v1"',
        }
        self.mock_aws_client.generate_presigned_url.return_value = "https://signed"

        # Act
        response = self.client.get(self._file_url(file.id, "download/"))

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"url": "https://signed"})

    def test_download_is_a_conflict_for_a_file_with_no_stored_object(self):
        for status in (AgentFile.Status.UPLOADING, AgentFile.Status.FAILED):
            with self.subTest(status=status):
                # Arrange
                file = make_file(self.owner, status=status)

                # Act
                response = self.client.get(self._file_url(file.id, "download/"))

                # Assert
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.data["code"], "file_unavailable")
        self.mock_aws_client.generate_presigned_url.assert_not_called()

    # -- sending files in a chat -------------------------------------------

    def _send(self, chat_id, **payload):
        with patch("research_ai.tasks.run_notebook_chat_turn_task.delay"):
            return self.client.post(
                f"{CHATS_URL}{chat_id}/messages/",
                {"message": "Summarize the attached proposal", **payload},
                format="json",
            )

    def test_a_message_carries_its_files_into_the_chat(self):
        # Arrange
        chat_id = self.client.post(CHATS_URL, {}, format="json").data["conversation_id"]
        file = make_file(self.owner, page_count=12, pages_without_text=5)

        # Act
        sent = self._send(chat_id, file_ids=[file.id])
        chat = self.client.get(f"{CHATS_URL}{chat_id}/")

        # Assert
        self.assertEqual(sent.status_code, 202)
        (message,) = chat.data["messages"]
        (attachment,) = message["attachments"]
        self.assertEqual(attachment["id"], file.id)
        self.assertEqual(attachment["filename"], "grant.pdf")
        self.assertEqual(attachment["page_count"], 12)
        self.assertEqual(attachment["pages_without_text"], 5)
        self.assertEqual(attachment["message_id"], message["id"])

    def test_a_message_with_an_unready_file_is_refused_whole(self):
        # Arrange
        chat_id = self.client.post(CHATS_URL, {}, format="json").data["conversation_id"]
        ready = make_file(self.owner)
        processing = make_file(self.owner, status=AgentFile.Status.PROCESSING)

        # Act
        response = self._send(chat_id, file_ids=[ready.id, processing.id])
        chat = self.client.get(f"{CHATS_URL}{chat_id}/")

        # Assert: nothing was recorded, so the user can simply resend.
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "attachment_not_ready")
        self.assertEqual(chat.data["messages"], [])
        self.assertEqual(chat.data["executions"], [])
        ready.refresh_from_db()
        self.assertIsNone(ready.message_id)

    def test_another_users_file_cannot_be_sent(self):
        # Arrange
        chat_id = self.client.post(CHATS_URL, {}, format="json").data["conversation_id"]
        foreign = make_file(self.other)

        # Act
        response = self._send(chat_id, file_ids=[foreign.id])

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "attachment_unavailable")
