"""Lifecycle of files users attach to Research AI chats.

A file moves UPLOADING -> PROCESSING -> READY or FAILED:

- ``create_upload`` validates the declared file and returns a presigned form
  upload; the browser sends the bytes straight to the private bucket, which
  enforces the size cap and content type.
- ``complete_upload`` confirms the object landed and queues extraction.
- ``process`` (worker) extracts the text the agent reads.

``purge`` deletes files never sent.
"""

import logging
import os
import uuid
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from research_ai.models import AgentFile
from research_ai.services.agent_files.config import AgentFileConfig
from research_ai.services.agent_files.extraction import (
    SUPPORTED_EXTENSIONS,
    UnreadableFileError,
    extract_text,
    kind_for_content_type,
    resolve_kind,
)
from researchhub.services.private_storage_service import (
    PresignedPost,
    PrivateStorageNotConfiguredError,
    PrivateStorageService,
)

logger = logging.getLogger(__name__)

_MAX_FILENAME_CHARS = 255
_PURGE_BATCH = 500
_UNSENT_STATUSES = (
    AgentFile.Status.UPLOADING,
    AgentFile.Status.PROCESSING,
    AgentFile.Status.READY,
)
_PROCESSING_FAILED = "This file could not be processed. Try uploading it again."
_PROCESSING_TIMED_OUT = "Processing this file took too long. Try uploading it again."


class AgentFileError(ValueError):
    """A file request that cannot be honored; ``code`` is for API clients."""

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


def public_file(file: AgentFile) -> dict:
    """The client-facing view of a file; never includes its text."""
    return {
        "id": file.id,
        "filename": file.filename,
        "content_type": file.content_type,
        "size_bytes": file.size_bytes,
        "status": file.status,
        "error": file.error or None,
        "page_count": file.page_count,
        "text_truncated": file.text_truncated,
        "conversation_id": file.conversation_id,
        "message_id": file.message_id,
        "created_date": file.created_date,
    }


def _display_name(filename: str) -> str:
    """The upload's base name, printable, on one line, within the column."""
    name = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = " ".join("".join(ch for ch in name if ch.isprintable()).split())
    if len(name) > _MAX_FILENAME_CHARS:
        stem, extension = os.path.splitext(name)
        name = stem[: _MAX_FILENAME_CHARS - len(extension)] + extension
    return name[:_MAX_FILENAME_CHARS]


def _key_name(filename: str) -> str:
    stem, extension = os.path.splitext(filename)
    return f"{slugify(stem)[:100] or 'file'}{extension.lower()}"


class AgentFileService:
    """Uploads, processing, attachment, and cleanup of chat files.

    ``storage`` and ``config`` are injectable for tests; they default to the
    private bucket and the settings-backed limits.
    """

    def __init__(
        self,
        *,
        storage: PrivateStorageService | None = None,
        config: AgentFileConfig | None = None,
    ):
        self.storage = PrivateStorageService() if storage is None else storage
        self._config = config

    @property
    def config(self) -> AgentFileConfig:
        return self._config or AgentFileConfig.from_settings()

    # -- request path -----------------------------------------------------

    def get_file(self, user, file_id: int) -> AgentFile | None:
        """``user``'s file ``file_id``, if any."""
        return AgentFile.objects.defer("text").filter(user=user, id=file_id).first()

    def create_upload(
        self, user, *, filename: str, size_bytes: int, content_type: str = ""
    ) -> tuple[AgentFile, PresignedPost]:
        """Record a new upload and return the presigned form to send it with.

        Raises ``AgentFileError`` for an unsupported, oversized, or excess
        file, and ``PrivateStorageNotConfiguredError`` without a bucket.
        """
        config = self.config
        filename = _display_name(filename)
        kind = resolve_kind(filename, content_type) if filename else None
        if kind is None:
            raise AgentFileError(
                "Upload a PDF, Word (.docx), or text file ("
                + ", ".join(SUPPORTED_EXTENSIONS)
                + ").",
                code="unsupported_file_type",
            )
        if size_bytes > config.max_file_bytes:
            raise AgentFileError(
                f"Files can be at most {config.max_file_bytes // (1024 * 1024)} MB.",
                code="file_too_large",
            )
        if not self.storage.configured:
            raise PrivateStorageNotConfiguredError("private storage is not set up")
        unsent = AgentFile.objects.filter(
            user=user, message__isnull=True, status__in=_UNSENT_STATUSES
        ).count()
        if unsent >= config.max_unsent_files:
            raise AgentFileError(
                "Too many files are waiting to be sent. Send or remove some first.",
                code="too_many_unsent_files",
            )
        key = (
            f"uploads/research_ai/users/{user.id}/{uuid.uuid4()}/{_key_name(filename)}"
        )
        upload = self.storage.presigned_post(
            key,
            content_type=kind.content_type,
            max_bytes=config.max_file_bytes,
            expires_in=config.upload_url_ttl_seconds,
        )
        file = AgentFile.objects.create(
            user=user,
            filename=filename,
            content_type=kind.content_type,
            size_bytes=size_bytes,
            storage_key=key,
        )
        return file, upload

    def complete_upload(self, file: AgentFile) -> AgentFile:
        """Confirm the upload reached storage and queue its processing.

        Idempotent: a file past UPLOADING is returned unchanged. Raises
        ``AgentFileError`` while the object is not in the bucket yet.
        """
        if file.status != AgentFile.Status.UPLOADING:
            return file
        stored = self.storage.head(file.storage_key)
        if stored is None:
            raise AgentFileError(
                "The upload has not reached storage. Upload the file, then retry.",
                code="upload_incomplete",
            )
        if stored.size_bytes > self.config.max_file_bytes:
            self._fail(file, _PROCESSING_FAILED)
        elif AgentFile.objects.filter(
            id=file.id, status=AgentFile.Status.UPLOADING
        ).update(
            status=AgentFile.Status.PROCESSING,
            size_bytes=stored.size_bytes,
            updated_date=timezone.now(),
        ):
            transaction.on_commit(lambda: self._schedule_processing(file.id))
        file.refresh_from_db()
        return file

    def refresh(self, file: AgentFile) -> AgentFile:
        """Fail a file whose processing outlived the timeout: its task is lost."""
        timeout = timedelta(seconds=self.config.processing_timeout_seconds)
        if (
            file.status == AgentFile.Status.PROCESSING
            and file.updated_date < timezone.now() - timeout
            and self._fail(file, _PROCESSING_TIMED_OUT)
        ):
            file.refresh_from_db()
        return file

    def delete(self, file: AgentFile) -> None:
        """Remove an unsent file and its object; sent files stay with their chat."""
        deleted, _ = AgentFile.objects.filter(id=file.id, message__isnull=True).delete()
        if not deleted:
            raise AgentFileError(
                "Files already sent in a chat cannot be removed.",
                code="attachment_sent",
            )
        self._delete_object(file.storage_key)

    def download_url(self, file: AgentFile) -> str:
        if file.status not in (AgentFile.Status.PROCESSING, AgentFile.Status.READY):
            raise AgentFileError(
                "This file is not available for download.", code="file_unavailable"
            )
        return self.storage.presigned_get(
            file.storage_key,
            filename=file.filename,
            expires_in=self.config.download_url_ttl_seconds,
        )

    # -- worker path ------------------------------------------------------

    def process(self, file_id: int) -> str | None:
        """Extract a PROCESSING file's text; returns its resulting status.

        ``None`` when the file is gone or not PROCESSING, so a duplicate or
        late task is a no-op.
        """
        file = AgentFile.objects.filter(
            id=file_id, status=AgentFile.Status.PROCESSING
        ).first()
        if file is None:
            return None
        config = self.config
        kind = kind_for_content_type(file.content_type)
        try:
            if kind is None:
                raise UnreadableFileError(_PROCESSING_FAILED)
            data = self.storage.read(file.storage_key, max_bytes=config.max_file_bytes)
            extracted = extract_text(data, kind, max_chars=config.max_text_chars)
        except UnreadableFileError as exc:
            self._fail(file, str(exc))
            return AgentFile.Status.FAILED
        except Exception:
            logger.exception("agent file %s could not be processed", file.id)
            self._fail(file, _PROCESSING_FAILED)
            return AgentFile.Status.FAILED
        AgentFile.objects.filter(id=file.id, status=AgentFile.Status.PROCESSING).update(
            status=AgentFile.Status.READY,
            text=extracted.text,
            text_truncated=extracted.truncated,
            page_count=extracted.page_count,
            updated_date=timezone.now(),
        )
        return AgentFile.Status.READY

    def purge(self) -> int:
        """Delete unsent files past their TTL."""
        cutoff = timezone.now() - timedelta(seconds=self.config.unsent_ttl_seconds)
        expired = Q(message__isnull=True, created_date__lt=cutoff)
        purged = 0
        for file_id, key in AgentFile.objects.filter(expired).values_list(
            "id", "storage_key"
        )[:_PURGE_BATCH]:
            # Re-checked per row: the file may have been sent since the scan.
            deleted, _ = AgentFile.objects.filter(expired, id=file_id).delete()
            if deleted:
                self._delete_object(key)
                purged += 1
        return purged

    # -- helpers ----------------------------------------------------------

    def _fail(self, file: AgentFile, message: str) -> bool:
        """Mark an unfinished file FAILED and drop its now useless object."""
        failed = AgentFile.objects.filter(
            id=file.id,
            status__in=[AgentFile.Status.UPLOADING, AgentFile.Status.PROCESSING],
        ).update(
            status=AgentFile.Status.FAILED,
            error=message[:255],
            text="",
            updated_date=timezone.now(),
        )
        if failed:
            self._delete_object(file.storage_key)
        return bool(failed)

    def _schedule_processing(self, file_id: int) -> None:
        # Imported here: ``tasks`` imports the chat services, which import this.
        from research_ai.tasks import process_agent_file_task

        try:
            process_agent_file_task.delay(file_id)
        except Exception:  # noqa: BLE001 - any enqueue failure
            logger.exception("could not queue agent file %s for processing", file_id)
            file = AgentFile.objects.filter(id=file_id).first()
            if file is not None:
                self._fail(file, _PROCESSING_FAILED)

    def _delete_object(self, key: str) -> None:
        try:
            self.storage.delete(key)
        except Exception:  # noqa: BLE001 - an orphaned object is not an outage
            logger.warning("could not delete agent file object %s", key, exc_info=True)
