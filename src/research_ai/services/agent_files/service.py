"""Lifecycle of files users attach to Research AI chats.

A file moves UPLOADING -> PROCESSING -> READY or FAILED:

- ``create_upload`` validates the declared file and returns a presigned form
  upload; the browser sends the bytes straight to the private bucket, which
  enforces the size cap and content type.
- ``complete_upload`` confirms the object landed and queues extraction.
- ``process`` (worker) extracts the text the agent reads; an image's is what
  OCR reads in it, which may be nothing.
- ``attach`` binds READY files to the user message they are sent with.
- ``message_attachments`` plans how each of a message's files reaches the model.

``purge`` deletes files never sent and files of removed conversations.
"""

import logging
import os
import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Length
from django.utils import timezone
from django.utils.text import slugify

from research_ai.models import AgentConversation, AgentConversationMessage, AgentFile
from research_ai.services.agent_files.config import AgentFileConfig
from research_ai.services.agent_files.delivery import (
    ConversationUsage,
    Delivery,
    DeliveryConfig,
    Document,
    TextDelivery,
    plan_delivery,
)
from research_ai.services.agent_files.extraction import (
    SUPPORTED_EXTENSIONS,
    UnreadableFileError,
    is_image_type,
    kind_for_content_type,
    resolve_kind,
)
from research_ai.services.agent_files.extraction_service import TextExtractionService
from research_ai.services.agent_files.mistral_ocr import MistralOcr
from research_ai.services.agent_files.page_images import page_image_keys
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


@dataclass(frozen=True)
class Attachment:
    """A file sent with a message and how it reaches the model."""

    file: AgentFile
    delivery: Delivery
    # The whole extracted text when it is delivered inline; not loaded otherwise.
    inline_text: str | None = None


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
        # Equals ``page_count`` when no page was readable; null when not counted.
        "pages_without_text": file.pages_without_text,
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


def _too_large(config: AgentFileConfig) -> str:
    return f"Files can be at most {config.max_file_bytes // (1024 * 1024)} MB."


def _key_name(filename: str) -> str:
    stem, extension = os.path.splitext(filename)
    return f"{slugify(stem)[:100] or 'file'}{extension.lower()}"


class AgentFileService:
    """Uploads, processing, attachment, and cleanup of chat files.

    ``storage``, ``config``, ``extraction`` and ``delivery_config`` are
    injectable for tests; they default to the private bucket, the
    settings-backed limits, extraction that reads scanned PDF pages with
    Mistral OCR when its key is set, and the settings-backed delivery policy.
    """

    def __init__(
        self,
        *,
        storage: PrivateStorageService | None = None,
        config: AgentFileConfig | None = None,
        extraction: TextExtractionService | None = None,
        delivery_config: DeliveryConfig | None = None,
    ):
        self.storage = PrivateStorageService() if storage is None else storage
        self._config = config
        self._extraction = extraction
        self._delivery_config = delivery_config

    @property
    def config(self) -> AgentFileConfig:
        return self._config or AgentFileConfig.from_settings()

    @property
    def extraction(self) -> TextExtractionService:
        return self._extraction or TextExtractionService(ocr=MistralOcr.from_settings())

    @property
    def delivery_config(self) -> DeliveryConfig:
        return self._delivery_config or DeliveryConfig.from_settings()

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
                "Upload a PDF, Word (.docx), text, or image file ("
                + ", ".join(SUPPORTED_EXTENSIONS)
                + ").",
                code="unsupported_file_type",
            )
        if size_bytes > config.max_file_bytes:
            raise AgentFileError(_too_large(config), code="file_too_large")
        if not self.storage.configured:
            raise PrivateStorageNotConfiguredError("private storage is not set up")
        key = (
            f"uploads/research_ai/users/{user.id}/{uuid.uuid4()}/{_key_name(filename)}"
        )
        upload = self.storage.presigned_post(
            key,
            content_type=kind.content_type,
            max_bytes=config.max_file_bytes,
            expires_in=config.upload_url_ttl_seconds,
        )
        with transaction.atomic():
            # The user row lock keeps simultaneous uploads within the cap.
            type(user)._default_manager.select_for_update().get(pk=user.pk)
            unsent = AgentFile.objects.filter(
                user=user, message__isnull=True, status__in=_UNSENT_STATUSES
            ).count()
            if unsent >= config.max_unsent_files:
                raise AgentFileError(
                    "Too many files are waiting to be sent. Send or remove some first.",
                    code="too_many_unsent_files",
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
        config = self.config
        if stored.size_bytes > config.max_file_bytes:
            self._fail(file, _too_large(config))
        elif AgentFile.objects.filter(
            id=file.id, status=AgentFile.Status.UPLOADING
        ).update(
            status=AgentFile.Status.PROCESSING,
            size_bytes=stored.size_bytes,
            etag=stored.etag,
            updated_date=timezone.now(),
        ):
            transaction.on_commit(lambda: self._schedule_processing(file.id))
        file.refresh_from_db()
        return file

    def refresh(self, file: AgentFile) -> AgentFile:
        """Fail a file whose task is lost: never picked up, or stalled mid-run."""
        if file.status != AgentFile.Status.PROCESSING:
            return file
        config = self.config
        if file.processing_started_date is None:
            since, allowed = file.updated_date, config.queue_timeout_seconds
        else:
            since, allowed = (
                file.processing_started_date,
                config.processing_timeout_seconds,
            )
        if timezone.now() - since > timedelta(seconds=allowed) and self._fail(
            file, _PROCESSING_TIMED_OUT
        ):
            file.refresh_from_db()
        return file

    def delete(self, file: AgentFile) -> None:
        """Remove an unsent file and its object; sent files stay with their chat.

        The row stays, ownerless, for ``purge``: the upload form may still be
        valid, and the row is the only record of its key.
        """
        removed = AgentFile.objects.filter(id=file.id, message__isnull=True).update(
            user=None,
            status=AgentFile.Status.FAILED,
            text="",
            updated_date=timezone.now(),
        )
        if not removed:
            raise AgentFileError(
                "Files already sent in a chat cannot be removed.",
                code="attachment_sent",
            )
        self._delete_object(file.storage_key)

    def download_url(self, file: AgentFile) -> str:
        """A short-lived URL for the object the file's text was read from."""
        available = file.status in (
            AgentFile.Status.PROCESSING,
            AgentFile.Status.READY,
        )
        if available:
            # The upload form outlives completion, so the object can be replaced.
            stored = self.storage.head(file.storage_key)
            available = stored is not None and stored.etag == file.etag
        if not available:
            raise AgentFileError(
                "This file is not available for download.", code="file_unavailable"
            )
        return self.storage.presigned_get(
            file.storage_key,
            filename=file.filename,
            expires_in=self.config.download_url_ttl_seconds,
        )

    def attach(
        self, message: AgentConversationMessage, file_ids: Iterable[int]
    ) -> list[AgentFile]:
        """Attach the message author's READY, unsent files to ``message``.

        Must run inside the caller's transaction, holding the conversation's
        row lock: the locks keep a file from being sent twice and the chat
        within its file cap. Raises ``AgentFileError``.
        """
        file_ids = list(dict.fromkeys(file_ids))
        if not file_ids:
            return []
        config = self.config
        if len(file_ids) > config.max_files_per_message:
            raise AgentFileError(
                f"A message can carry at most {config.max_files_per_message} files.",
                code="too_many_attachments",
            )
        conversation = message.conversation
        sent = AgentFile.objects.filter(conversation=conversation).count()
        if sent + len(file_ids) > config.max_files_per_conversation:
            raise AgentFileError(
                f"A chat can hold at most {config.max_files_per_conversation} "
                "files. Start a new chat to attach more.",
                code="too_many_attachments",
            )
        files = {
            file.id: file
            for file in AgentFile.objects.select_for_update()
            .defer("text")
            # A removed file has no owner; a chat without one must not match it.
            .filter(id__in=file_ids, user_id=conversation.user_id, user__isnull=False)
        }
        for file_id in file_ids:
            file = files.get(file_id)
            if file is None or file.message_id is not None:
                raise AgentFileError(
                    f"File {file_id} cannot be attached.",
                    code="attachment_unavailable",
                )
            if file.status == AgentFile.Status.FAILED:
                raise AgentFileError(
                    f'"{file.filename}" could not be read: {file.error}',
                    code="attachment_failed",
                )
            if file.status != AgentFile.Status.READY:
                raise AgentFileError(
                    f'"{file.filename}" is still being processed.',
                    code="attachment_not_ready",
                )
        AgentFile.objects.filter(id__in=file_ids).update(
            message=message, conversation=conversation, updated_date=timezone.now()
        )
        return [files[file_id] for file_id in file_ids]

    def attachments_by_message(
        self, conversation: AgentConversation
    ) -> dict[int, list[dict]]:
        """Public views of the conversation's sent files, keyed by message id."""
        grouped: dict[int, list[dict]] = defaultdict(list)
        for file in (
            AgentFile.objects.defer("text")
            .filter(conversation=conversation, message__isnull=False)
            .order_by("id")
        ):
            grouped[file.message_id].append(public_file(file))
        return grouped

    def message_attachments(
        self,
        message: AgentConversationMessage,
        *,
        vision: bool,
        used: ConversationUsage | None = None,
    ) -> list[Attachment]:
        """The READY files sent with ``message`` and how each reaches the model.

        ``vision`` is whether the conversation's model accepts images; ``used``
        is what its context carried before this message. Files carry
        ``text_chars``; text is loaded only for those delivered inline.
        """
        files = list(
            AgentFile.objects.defer("text")
            .filter(message=message, status=AgentFile.Status.READY)
            .annotate(text_chars=Length("text"))
            .order_by("id")
        )
        deliveries = plan_delivery(
            [
                Document(
                    text_chars=file.text_chars,
                    page_count=file.page_count,
                    image=is_image_type(file.content_type),
                )
                for file in files
            ],
            vision=vision,
            config=self.delivery_config,
            used=used,
        )
        inline_ids = [
            file.id
            for file, delivery in zip(files, deliveries, strict=True)
            if delivery.text == TextDelivery.INLINE
        ]
        texts = dict(
            AgentFile.objects.filter(id__in=inline_ids).values_list("id", "text")
        )
        return [
            Attachment(file=file, delivery=delivery, inline_text=texts.get(file.id))
            for file, delivery in zip(files, deliveries, strict=True)
        ]

    # -- worker path ------------------------------------------------------

    def process(self, file_id: int) -> str | None:
        """Extract a PROCESSING file's text; returns its resulting status.

        ``None`` when the file is gone or not PROCESSING, so a duplicate or
        late task is a no-op.
        """
        processing = AgentFile.objects.filter(
            id=file_id, status=AgentFile.Status.PROCESSING
        )
        # Claiming the file starts its processing timeout and stops a second run.
        if not processing.filter(processing_started_date__isnull=True).update(
            processing_started_date=timezone.now()
        ):
            return None
        file = processing.first()
        if file is None:
            return None
        config = self.config
        kind = kind_for_content_type(file.content_type)
        try:
            if kind is None:
                raise UnreadableFileError(_PROCESSING_FAILED)
            data = self.storage.read(
                file.storage_key, max_bytes=config.max_file_bytes, if_match=file.etag
            )
            extracted = self.extraction.extract(
                data, kind, max_chars=config.max_text_chars
            )
        except UnreadableFileError as exc:
            self._fail(file, str(exc))
            return AgentFile.Status.FAILED
        except Exception:
            logger.exception("agent file %s could not be processed", file.id)
            self._fail(file, _PROCESSING_FAILED)
            return AgentFile.Status.FAILED
        # Matches nothing when the file was removed or timed out meanwhile.
        readied = processing.update(
            status=AgentFile.Status.READY,
            text=extracted.text,
            text_truncated=extracted.truncated,
            page_count=extracted.page_count,
            # Only a PDF has pages to count.
            pages_without_text=(
                None
                if extracted.page_count is None
                else len(extracted.pages_without_text)
            ),
            updated_date=timezone.now(),
        )
        return AgentFile.Status.READY if readied else None

    def purge(self) -> int:
        """Delete expired unsent files, removed files and removed chats' files.

        The object goes first, so a failed delete leaves the row for a retry.
        """
        config = self.config
        now = timezone.now()
        expired = (
            Q(
                message__isnull=True,
                created_date__lt=now - timedelta(seconds=config.unsent_ttl_seconds),
            )
            | Q(
                # Kept until the upload form expires, so a late upload is deleted too.
                user__isnull=True,
                created_date__lt=now - timedelta(seconds=config.upload_url_ttl_seconds),
            )
            | Q(conversation__is_removed=True)
        )
        purged = 0
        file_ids = AgentFile.objects.filter(expired).order_by("id")
        for file_id in file_ids.values_list("id", flat=True)[:_PURGE_BATCH]:
            with transaction.atomic():
                # Re-checked under a lock: the file may have been sent since the scan.
                file = (
                    AgentFile.objects.select_for_update(of=("self",))
                    .only("storage_key", "content_type", "page_count")
                    .filter(expired, id=file_id)
                    .first()
                )
                if file is None:
                    continue
                try:
                    # The original goes first: without it no page renders again.
                    self.storage.delete(file.storage_key)
                    self.storage.delete_many(page_image_keys(file))
                except Exception:  # noqa: BLE001 - the row stays for the next run
                    logger.warning(
                        "could not delete agent file object %s",
                        file.storage_key,
                        exc_info=True,
                    )
                    continue
                file.delete()
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
