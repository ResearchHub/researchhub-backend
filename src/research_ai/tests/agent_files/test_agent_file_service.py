from datetime import timedelta
from unittest.mock import Mock, patch

import responses
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from research_ai.models import AgentFile
from research_ai.services.agent_files import (
    AgentFileConfig,
    AgentFileError,
    AgentFileService,
)
from research_ai.services.agent_files.extraction import NO_TEXT_LAYER, OCR_NOTE
from research_ai.services.agent_files.mistral_ocr import API_URL as MISTRAL_OCR_URL
from research_ai.services.agent_persistence import AgentConversationService
from research_ai.tests.agent_files.helpers import (
    SCAN,
    make_file,
    pdf_bytes,
    pdf_with_scans,
)
from researchhub.services.private_storage_service import (
    PresignedPost,
    PrivateStorageNotConfiguredError,
    PrivateStorageService,
    StoredObject,
)

CONFIG = AgentFileConfig(
    max_file_bytes=1000,
    max_text_chars=10_000,
    max_unsent_files=3,
)
UPLOAD = PresignedPost("https://bucket.s3.amazonaws.com/", {"key": "k"})
PROCESS_DELAY = "research_ai.tasks.process_agent_file_task.delay"


class AgentFileServiceTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="owner@researchhub_test.com",
            password="password",
            email="owner@researchhub_test.com",
        )
        self.other = user_model.objects.create_user(
            username="other@researchhub_test.com",
            password="password",
            email="other@researchhub_test.com",
        )
        self.storage = Mock(spec=PrivateStorageService)
        self.storage.configured = True
        self.storage.presigned_post.return_value = UPLOAD
        self.service = AgentFileService(storage=self.storage, config=CONFIG)
        conversations = AgentConversationService()
        self.conversation = conversations.create(
            user=self.user, workflow="assistant_chat"
        )
        self.message = conversations.add_human_message(self.conversation, "Read it")

    def _age(self, file, *, field, seconds):
        AgentFile.objects.filter(id=file.id).update(
            **{field: timezone.now() - timedelta(seconds=seconds)}
        )
        file.refresh_from_db()

    # -- creating uploads -------------------------------------------------

    def test_create_upload_records_the_file_and_signs_a_bounded_form(self):
        # Act
        file, upload = self.service.create_upload(
            self.user, filename="Aims.PDF", size_bytes=500, content_type=""
        )

        # Assert
        self.assertEqual(upload, UPLOAD)
        self.assertEqual(file.status, AgentFile.Status.UPLOADING)
        self.assertEqual(file.filename, "Aims.PDF")
        self.assertEqual(file.content_type, "application/pdf")
        self.assertEqual(file.size_bytes, 500)
        self.assertIsNone(file.message_id)
        prefix = f"uploads/research_ai/users/{self.user.id}/"
        self.assertTrue(file.storage_key.startswith(prefix))
        self.assertTrue(file.storage_key.endswith("/aims.pdf"))
        self.storage.presigned_post.assert_called_once_with(
            file.storage_key,
            content_type="application/pdf",
            max_bytes=CONFIG.max_file_bytes,
            expires_in=CONFIG.upload_url_ttl_seconds,
        )

    def test_create_upload_keeps_only_a_clean_base_name(self):
        # Act
        file, _upload = self.service.create_upload(
            self.user, filename="C:\\fakepath\\My\tGrant  (v2).docx", size_bytes=10
        )

        # Assert
        self.assertEqual(file.filename, "MyGrant (v2).docx")
        self.assertTrue(file.storage_key.endswith("/mygrant-v2.docx"))

    def test_create_upload_refuses_unsupported_and_oversized_files(self):
        cases = [
            ("slides.pptx", 10, "unsupported_file_type"),
            ("", 10, "unsupported_file_type"),
            ("grant.pdf", CONFIG.max_file_bytes + 1, "file_too_large"),
        ]
        for filename, size_bytes, code in cases:
            with self.subTest(filename=filename, size_bytes=size_bytes):
                # Act
                with self.assertRaises(AgentFileError) as raised:
                    self.service.create_upload(
                        self.user, filename=filename, size_bytes=size_bytes
                    )

                # Assert
                self.assertEqual(raised.exception.code, code)
        self.assertFalse(AgentFile.objects.exists())

    def test_create_upload_caps_files_waiting_to_be_sent(self):
        # Arrange: failed and sent files do not count against the cap.
        make_file(self.user, status=AgentFile.Status.UPLOADING)
        make_file(self.user, status=AgentFile.Status.READY)
        make_file(self.user, status=AgentFile.Status.FAILED)
        make_file(self.user, message=self.message)
        make_file(self.other, status=AgentFile.Status.READY)

        # Act
        self.service.create_upload(self.user, filename="a.txt", size_bytes=1)
        with self.assertRaises(AgentFileError) as raised:
            self.service.create_upload(self.user, filename="b.txt", size_bytes=1)

        # Assert
        self.assertEqual(raised.exception.code, "too_many_unsent_files")

    def test_create_upload_needs_the_private_bucket(self):
        # Arrange
        self.storage.configured = False

        # Act / Assert
        with self.assertRaises(PrivateStorageNotConfiguredError):
            self.service.create_upload(self.user, filename="a.pdf", size_bytes=1)
        self.assertFalse(AgentFile.objects.exists())

    # -- completing uploads -----------------------------------------------

    def test_complete_upload_queues_processing_once(self):
        # Arrange
        file = make_file(self.user, status=AgentFile.Status.UPLOADING, size_bytes=1)
        self.storage.head.return_value = StoredObject(500, "application/pdf", '"v1"')

        # Act
        with (
            patch(PROCESS_DELAY) as delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            completed = self.service.complete_upload(file)
            repeated = self.service.complete_upload(completed)

        # Assert
        self.assertEqual(completed.status, AgentFile.Status.PROCESSING)
        self.assertEqual(completed.size_bytes, 500)
        self.assertEqual(completed.etag, '"v1"')
        self.assertEqual(repeated.status, AgentFile.Status.PROCESSING)
        delay.assert_called_once_with(file.id)

    def test_complete_upload_waits_for_the_object(self):
        # Arrange
        file = make_file(self.user, status=AgentFile.Status.UPLOADING)
        self.storage.head.return_value = None

        # Act
        with self.assertRaises(AgentFileError) as raised:
            self.service.complete_upload(file)

        # Assert
        self.assertEqual(raised.exception.code, "upload_incomplete")
        file.refresh_from_db()
        self.assertEqual(file.status, AgentFile.Status.UPLOADING)

    def test_complete_upload_fails_an_oversized_object(self):
        # Arrange
        file = make_file(self.user, status=AgentFile.Status.UPLOADING)
        self.storage.head.return_value = StoredObject(5000, "application/pdf")

        # Act
        completed = self.service.complete_upload(file)

        # Assert
        self.assertEqual(completed.status, AgentFile.Status.FAILED)
        self.assertIn("Files can be at most", completed.error)
        self.storage.delete.assert_called_once_with(file.storage_key)

    def test_a_refused_enqueue_fails_the_file(self):
        # Arrange
        file = make_file(self.user, status=AgentFile.Status.UPLOADING)
        self.storage.head.return_value = StoredObject(10, "application/pdf")

        # Act
        with (
            patch(PROCESS_DELAY, side_effect=ConnectionError("broker down")),
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.service.complete_upload(file)

        # Assert
        file.refresh_from_db()
        self.assertEqual(file.status, AgentFile.Status.FAILED)
        self.assertIn("could not be processed", file.error)

    # -- processing ---------------------------------------------------------

    def test_process_extracts_the_text_the_agent_reads(self):
        # Arrange
        file = make_file(
            self.user, status=AgentFile.Status.PROCESSING, text="", etag='"v1"'
        )
        self.storage.read.return_value = pdf_bytes("Specific aims", "Budget")

        # Act
        status = self.service.process(file.id)

        # Assert
        file.refresh_from_db()
        self.assertEqual(status, AgentFile.Status.READY)
        self.assertEqual(file.status, AgentFile.Status.READY)
        self.assertEqual(file.text, "[Page 1]\nSpecific aims\n\n[Page 2]\nBudget")
        self.assertEqual(file.page_count, 2)
        self.assertFalse(file.text_truncated)
        self.assertIsNotNone(file.processing_started_date)
        self.storage.read.assert_called_once_with(
            file.storage_key, max_bytes=CONFIG.max_file_bytes, if_match='"v1"'
        )

    def test_process_reports_why_a_file_is_unreadable(self):
        # Arrange
        file = make_file(self.user, status=AgentFile.Status.PROCESSING, text="")
        self.storage.read.return_value = pdf_bytes("")

        # Act
        status = self.service.process(file.id)

        # Assert
        file.refresh_from_db()
        self.assertEqual(status, AgentFile.Status.FAILED)
        self.assertIn("no selectable text", file.error)
        self.storage.delete.assert_called_once_with(file.storage_key)

    @override_settings(MISTRAL_API_KEY="test-key")
    @responses.activate
    def test_process_reads_scanned_pages_by_ocr_when_the_key_is_set(self):
        # Arrange
        file = make_file(self.user, status=AgentFile.Status.PROCESSING, text="")
        self.storage.read.return_value = pdf_with_scans("Specific aims", SCAN)
        responses.post(
            MISTRAL_OCR_URL, json={"pages": [{"index": 0, "markdown": "Budget"}]}
        )

        # Act
        status = self.service.process(file.id)

        # Assert
        file.refresh_from_db()
        self.assertEqual(status, AgentFile.Status.READY)
        self.assertEqual(
            file.text, f"[Page 1]\nSpecific aims\n\n[Page 2]\n{OCR_NOTE}\nBudget"
        )
        self.assertEqual(len(responses.calls), 1)

    @override_settings(MISTRAL_API_KEY="")
    @responses.activate
    def test_process_only_marks_scanned_pages_without_the_key(self):
        # Arrange
        file = make_file(self.user, status=AgentFile.Status.PROCESSING, text="")
        self.storage.read.return_value = pdf_with_scans("Specific aims", SCAN)

        # Act
        status = self.service.process(file.id)

        # Assert
        file.refresh_from_db()
        self.assertEqual(status, AgentFile.Status.READY)
        self.assertEqual(
            file.text, f"[Page 1]\nSpecific aims\n\n[Page 2]\n{NO_TEXT_LAYER}"
        )
        self.assertEqual(len(responses.calls), 0)

    def test_process_fails_generically_when_storage_breaks(self):
        # Arrange
        file = make_file(self.user, status=AgentFile.Status.PROCESSING, text="")
        self.storage.read.side_effect = RuntimeError("s3 unavailable")

        # Act
        status = self.service.process(file.id)

        # Assert
        file.refresh_from_db()
        self.assertEqual(status, AgentFile.Status.FAILED)
        self.assertEqual(
            file.error, "This file could not be processed. Try uploading it again."
        )

    def test_process_is_a_no_op_unless_the_file_is_processing(self):
        # Arrange
        file = make_file(self.user, status=AgentFile.Status.READY)

        # Act
        status = self.service.process(file.id)

        # Assert
        self.assertIsNone(status)
        self.storage.read.assert_not_called()

    def test_process_runs_a_file_only_once(self):
        # Arrange
        file = make_file(
            self.user,
            status=AgentFile.Status.PROCESSING,
            processing_started_date=timezone.now(),
        )

        # Act
        status = self.service.process(file.id)

        # Assert
        self.assertIsNone(status)
        self.storage.read.assert_not_called()

    def test_process_keeps_no_text_for_a_file_removed_meanwhile(self):
        # Arrange
        file = make_file(self.user, status=AgentFile.Status.PROCESSING, text="")

        def read_after_removal(*_args, **_kwargs):
            self.service.delete(file)
            return pdf_bytes("Specific aims")

        self.storage.read.side_effect = read_after_removal

        # Act
        status = self.service.process(file.id)

        # Assert
        file.refresh_from_db()
        self.assertIsNone(status)
        self.assertEqual(file.text, "")

    def test_refresh_fails_a_file_whose_processing_stalled(self):
        # Arrange
        stalled = make_file(self.user, status=AgentFile.Status.PROCESSING)
        self._age(
            stalled,
            field="processing_started_date",
            seconds=CONFIG.processing_timeout_seconds + 1,
        )
        recent = make_file(
            self.user,
            status=AgentFile.Status.PROCESSING,
            processing_started_date=timezone.now(),
        )

        # Act
        stalled = self.service.refresh(stalled)
        recent = self.service.refresh(recent)

        # Assert
        self.assertEqual(stalled.status, AgentFile.Status.FAILED)
        self.assertIn("took too long", stalled.error)
        self.assertEqual(recent.status, AgentFile.Status.PROCESSING)

    def test_refresh_allows_a_queued_file_longer_than_a_running_one(self):
        # Arrange
        waiting = make_file(self.user, status=AgentFile.Status.PROCESSING)
        self._age(
            waiting,
            field="updated_date",
            seconds=CONFIG.processing_timeout_seconds + 1,
        )
        lost = make_file(self.user, status=AgentFile.Status.PROCESSING)
        self._age(lost, field="updated_date", seconds=CONFIG.queue_timeout_seconds + 1)

        # Act
        waiting = self.service.refresh(waiting)
        lost = self.service.refresh(lost)

        # Assert
        self.assertEqual(waiting.status, AgentFile.Status.PROCESSING)
        self.assertEqual(lost.status, AgentFile.Status.FAILED)
        self.assertIn("took too long", lost.error)

    # -- removal, download, purge -------------------------------------------

    def test_delete_removes_an_unsent_file_and_its_object(self):
        # Arrange
        file = make_file(self.user)

        # Act
        self.service.delete(file)

        # Assert: the row stays, ownerless and empty, for the purge.
        self.assertIsNone(self.service.get_file(self.user, file.id))
        file.refresh_from_db()
        self.assertIsNone(file.user_id)
        self.assertEqual(file.text, "")
        self.storage.delete.assert_called_once_with(file.storage_key)

    def test_delete_refuses_a_sent_file(self):
        # Arrange
        file = make_file(self.user, message=self.message)

        # Act
        with self.assertRaises(AgentFileError) as raised:
            self.service.delete(file)

        # Assert
        self.assertEqual(raised.exception.code, "attachment_sent")
        self.assertTrue(AgentFile.objects.filter(id=file.id).exists())
        self.storage.delete.assert_not_called()

    def test_download_url_is_only_issued_for_stored_files(self):
        # Arrange
        self.storage.presigned_get.return_value = "https://signed"
        self.storage.head.return_value = StoredObject(100, "application/pdf", '"v1"')
        ready = make_file(self.user, etag='"v1"')
        uploading = make_file(self.user, status=AgentFile.Status.UPLOADING)

        # Act
        url = self.service.download_url(ready)
        with self.assertRaises(AgentFileError) as raised:
            self.service.download_url(uploading)

        # Assert
        self.assertEqual(url, "https://signed")
        self.storage.presigned_get.assert_called_once_with(
            ready.storage_key,
            filename="grant.pdf",
            expires_in=CONFIG.download_url_ttl_seconds,
        )
        self.assertEqual(raised.exception.code, "file_unavailable")

    def test_download_url_is_refused_once_the_object_changed(self):
        # Arrange
        file = make_file(self.user, etag='"v1"')
        for stored in (StoredObject(100, "application/pdf", '"v2"'), None):
            with self.subTest(stored=stored):
                self.storage.head.return_value = stored

                # Act
                with self.assertRaises(AgentFileError) as raised:
                    self.service.download_url(file)

                # Assert
                self.assertEqual(raised.exception.code, "file_unavailable")
        self.storage.presigned_get.assert_not_called()

    def test_purge_deletes_stale_unsent_files(self):
        # Arrange
        stale = make_file(self.user)
        self._age(stale, field="created_date", seconds=CONFIG.unsent_ttl_seconds + 1)
        fresh = make_file(self.user)
        sent = make_file(self.user, message=self.message)
        self._age(sent, field="created_date", seconds=CONFIG.unsent_ttl_seconds + 1)

        # Act
        purged = self.service.purge()

        # Assert
        self.assertEqual(purged, 1)
        self.assertEqual(
            set(AgentFile.objects.values_list("id", flat=True)), {fresh.id, sent.id}
        )
        self.storage.delete.assert_called_once_with(stale.storage_key)

    def test_purge_deletes_removed_files_once_their_upload_form_expires(self):
        # Arrange
        expired = make_file(self.user)
        self._age(
            expired, field="created_date", seconds=CONFIG.upload_url_ttl_seconds + 1
        )
        uploadable = make_file(self.user)
        self.service.delete(expired)
        self.service.delete(uploadable)
        self.storage.delete.reset_mock()

        # Act
        purged = self.service.purge()

        # Assert: the object is deleted again, in case it was uploaded since.
        self.assertEqual(purged, 1)
        self.assertEqual(
            list(AgentFile.objects.values_list("id", flat=True)), [uploadable.id]
        )
        self.storage.delete.assert_called_once_with(expired.storage_key)

    def test_purge_keeps_a_file_whose_object_could_not_be_deleted(self):
        # Arrange
        stale = make_file(self.user)
        self._age(stale, field="created_date", seconds=CONFIG.unsent_ttl_seconds + 1)
        self.storage.delete.side_effect = RuntimeError("s3 unavailable")

        # Act
        purged = self.service.purge()

        # Assert
        self.assertEqual(purged, 0)
        self.assertTrue(AgentFile.objects.filter(id=stale.id).exists())

    def test_a_hard_deleted_account_leaves_its_files_for_the_purge(self):
        # Arrange
        file = make_file(self.other)
        self._age(file, field="created_date", seconds=CONFIG.upload_url_ttl_seconds + 1)

        # Act
        self.other.delete(soft=False)
        kept = AgentFile.objects.filter(id=file.id, user__isnull=True).exists()
        purged = self.service.purge()

        # Assert
        self.assertTrue(kept)
        self.assertEqual(purged, 1)
        self.storage.delete.assert_called_once_with(file.storage_key)
