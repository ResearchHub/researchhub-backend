from unittest.mock import patch

from botocore.exceptions import ClientError
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from research_ai.models import AgentConversation, AgentFile
from research_ai.services.agent_persistence import AgentConversationService
from research_ai.tests.agent_files.helpers import make_file
from utils.test_helpers import AWSMockMixin

FILES_URL = "/api/research_ai/files/"
CHATS_URL = "/api/research_ai/assistant/chats/"
BUCKET = "researchhub-test-private-storage"


@override_settings(AWS_PRIVATE_STORAGE_BUCKET_NAME=BUCKET)
class AgentFileViewTests(AWSMockMixin, APITestCase):
    def setUp(self):
        super().setUp()
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
        self.assertFalse(AgentFile.objects.filter(id=unsent.id).exists())
        self.mock_aws_client.delete_object.assert_called_once_with(
            Bucket=BUCKET, Key=unsent.storage_key
        )
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.data["code"], "attachment_sent")

    def test_download_returns_a_short_lived_url(self):
        # Arrange
        file = make_file(self.owner)
        self.mock_aws_client.generate_presigned_url.return_value = "https://signed"

        # Act
        response = self.client.get(self._file_url(file.id, "download/"))

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"url": "https://signed"})
