"""Generate a cover banner for a proposal or RFP through OpenRouter.

``start`` records a request and queues it; a worker calls ``run``, which asks
OpenRouter for one banner and stores it, as a JPEG, in the default storage
under the same key layout as user-uploaded post covers. When the request is for
a note whose chat agent recorded a cover logo (an image the user attached in
the chat), that image is sent along as a reference to place in the banner. The
client polls the request until it completes, shows the banner, and sends its
key as the post's ``image``.

The note's chat calls ``generate_for_note`` instead: it already runs on a
worker, so it generates in place and saves the banner as the draft's cover.
"""

import base64
import io
import logging
import uuid
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone
from PIL import Image

from note.models import Note
from research_ai.models import AgentFile, CoverImageGeneration, NoteCoverLogo
from research_ai.prompts.cover_image_prompts import CoverImagePrompts
from research_ai.services.agent.types import TurnUsage
from research_ai.services.openrouter_image_client import (
    GeneratedImage,
    OpenRouterImageClient,
)
from research_ai.services.usage_budget import (
    UsageLimitExceededError,
    check_spend_admission,
    record,
)
from research_ai.services.usage_budget.config import COVER_IMAGE_FEATURE
from researchhub.services.private_storage_service import PrivateStorageService

logger = logging.getLogger(__name__)


class CoverImageGenerationEnqueueError(RuntimeError):
    """The request was recorded but could not be queued; it is marked failed."""


class CoverImageNoteError(ValueError):
    """The note does not exist or the user cannot open it."""


class CoverImageGenerationBusyError(RuntimeError):
    """The user already has as many requests generating as they may."""


def _enqueue_cover_image_generation(generation_id: int) -> None:
    # Import lazily because tasks imports this module.
    from research_ai.tasks import generate_cover_image_task

    generate_cover_image_task.delay(generation_id)


class CoverImageService:
    # Sunburst is the precision tier of GPT Image 2.5, for legible banner text.
    MODEL = "openai/gpt-image-2.5-sunburst"
    # Pages show the banner cut to about 3:1; 21:9 is the widest ratio the
    # model offers, and the prompt keeps the text clear of the cut.
    ASPECT_RATIO = "21:9"
    QUALITY = "medium"
    JPEG_QUALITY = 90
    # A logo is scaled down to this before it is sent; it only needs to be legible.
    LOGO_MAX_SIDE = 1024
    LOGO_MAX_BYTES = 25 * 1024 * 1024

    ACTIVE_STATUSES = (
        CoverImageGeneration.Status.PENDING,
        CoverImageGeneration.Status.PROCESSING,
    )
    # Generating takes under a minute; a request still queued, or still
    # processing, well past that lost its worker, and is reported failed so the
    # client stops waiting.
    STALE_AFTER = timedelta(minutes=10)
    # The worker's ceiling, above the image call's own client timeout.
    TIME_LIMIT_SECONDS = 6 * 60
    # Spend is recorded only once an image comes back, so the daily budget
    # cannot see requests still generating; this bounds them instead.
    MAX_ACTIVE_PER_USER = 2

    GENERATION_FAILED_MESSAGE = "Could not generate a cover image. Please try again."

    def __init__(
        self,
        client: OpenRouterImageClient | None = None,
        storage=None,
        enqueue: Callable[[int], None] | None = None,
        private_storage: PrivateStorageService | None = None,
    ):
        self._client = client
        self.api_key = getattr(settings, "OPENROUTER_API_KEY", "") or ""
        self.storage = storage if storage is not None else default_storage
        # Chat attachments, the cover logo among them, live in the private bucket.
        self.private_storage = (
            private_storage if private_storage is not None else PrivateStorageService()
        )
        self.enqueue = (
            enqueue if enqueue is not None else _enqueue_cover_image_generation
        )

    @property
    def configured(self) -> bool:
        return self._client is not None or bool(self.api_key)

    @property
    def client(self) -> OpenRouterImageClient:
        # Built on first use, so polling a request opens no HTTP client.
        if self._client is None:
            self._client = OpenRouterImageClient(self.api_key)
        return self._client

    def start(
        self,
        *,
        user,
        document_type: str,
        title: str,
        subtitle: str = "",
        organization: str = "",
        funding_amount_usd: Decimal | None = None,
        note_id: int | None = None,
    ) -> CoverImageGeneration:
        """Record a generation request and queue it for a worker.

        With ``note_id``, the covers use that note's cover logo, if its chat
        recorded one. Raises ``UsageLimitExceededError`` once the user's daily
        AI budget is spent; generating spends it, in dollars only. Raises
        ``CoverImageGenerationBusyError`` while the user already has
        ``MAX_ACTIVE_PER_USER`` requests generating.
        """
        check_spend_admission(user)
        note = self._readable_note(user, note_id) if note_id is not None else None
        if note_id is not None and note is None:
            raise CoverImageNoteError("Note not found.")

        with transaction.atomic():
            # Locking the user makes two requests at once count each other.
            get_user_model().objects.select_for_update().filter(id=user.id).first()
            if self._active_count(user) >= self.MAX_ACTIVE_PER_USER:
                raise CoverImageGenerationBusyError(
                    "A cover image is already generating."
                )
            generation = CoverImageGeneration.objects.create(
                created_by=user,
                note=note,
                document_type=document_type,
                title=title,
                subtitle=subtitle,
                organization=organization,
                funding_amount_usd=funding_amount_usd,
                logo_file=self.cover_logo(note) if note is not None else None,
            )
        try:
            self.enqueue(generation.id)
        except Exception as error:  # noqa: BLE001 - broker clients vary
            logger.exception("could not queue cover image generation %s", generation.id)
            self._fail(generation, "Could not queue cover image generation")
            raise CoverImageGenerationEnqueueError(str(error)) from error
        return generation

    def generate_for_note(self, user, note: Note) -> CoverImageGeneration:
        """Generate a cover from a draft's saved details and make it its cover.

        Runs in the caller, which must be a worker with the OpenRouter key: the
        note's chat. Replaces any cover the draft had. Raises
        ``UsageLimitExceededError`` once the user's daily AI budget is spent.
        """
        check_spend_admission(user)
        generation = CoverImageGeneration.objects.create(
            created_by=user,
            note=note,
            logo_file=self.cover_logo(note),
            **self.note_cover_text(note),
        )
        self.run(generation.id)
        generation.refresh_from_db()
        if generation.status == CoverImageGeneration.Status.COMPLETED:
            note.image = generation.image_key
            note.preview_img = self.image_url(generation.image_key)
            note.save(update_fields=["image", "preview_img", "updated_date"])
        return generation

    @staticmethod
    def note_cover_text(note: Note) -> dict:
        """What a cover for the draft shows, from its saved details, as the
        publishing form would send it."""
        text = {"document_type": note.document_type, "title": note.title.strip()}
        amount, currency = None, ""
        if note.document_type == CoverImageGeneration.DocumentType.GRANT:
            details = getattr(note, "grant_settings", None)
            if details is not None:
                text["subtitle"] = details.description.strip()
                text["organization"] = details.organization.strip()[
                    : CoverImageGeneration._meta.get_field("organization").max_length
                ]
                amount, currency = details.amount, details.currency
        else:
            details = getattr(note, "preregistration_settings", None)
            if details is not None:
                amount, currency = details.goal_amount, details.goal_currency
        # The banner states the amount in dollars, so only a dollar amount shows.
        if amount and currency in ("", "USD"):
            text["funding_amount_usd"] = amount
        return text

    def get_for_user(self, user, generation_id: int) -> CoverImageGeneration | None:
        """The user's request, with one whose worker was lost marked failed."""
        generation = CoverImageGeneration.objects.filter(
            id=generation_id, created_by=user
        ).first()
        if generation is not None and self._is_stale(generation):
            self._fail(generation, "Cover image generation timed out")
            generation.refresh_from_db()
        return generation

    def _active_count(self, user) -> int:
        """The user's requests still generating, leaving out ones whose worker
        was lost, which are reported failed when next read."""
        return CoverImageGeneration.objects.filter(
            created_by=user,
            status__in=self.ACTIVE_STATUSES,
            updated_date__gte=timezone.now() - self.STALE_AFTER,
        ).count()

    def _is_stale(self, generation: CoverImageGeneration) -> bool:
        # A queued request is timed from its creation; a processing one from
        # its claim, which is its last update until it finishes.
        since = {
            CoverImageGeneration.Status.PENDING: generation.created_date,
            CoverImageGeneration.Status.PROCESSING: generation.updated_date,
        }.get(generation.status)
        return since is not None and since < timezone.now() - self.STALE_AFTER

    def run(self, generation_id: int) -> None:
        """Generate and store the banner for a queued request."""
        now = timezone.now()
        pending = CoverImageGeneration.objects.filter(
            id=generation_id, status=CoverImageGeneration.Status.PENDING
        )
        # A request queued too long ago no longer counts against the user's
        # limit, so it is failed rather than generated: running it anyway
        # would let a backed-up queue pay for more than the limit allows.
        expired = pending.filter(created_date__lt=now - self.STALE_AFTER).update(
            status=CoverImageGeneration.Status.FAILED,
            error="Cover image generation timed out",
            updated_date=now,
        )
        if expired:
            logger.warning("cover image generation %s timed out", generation_id)
            return
        claimed = pending.update(
            status=CoverImageGeneration.Status.PROCESSING, updated_date=now
        )
        if not claimed:
            return
        generation = CoverImageGeneration.objects.get(id=generation_id)
        # The key is set on the workers, not the API servers that queue this.
        if not self.configured:
            self._fail(generation, "OpenRouter is not configured")
            return
        # The budget may have been spent since the request was queued.
        try:
            check_spend_admission(generation.created_by)
        except UsageLimitExceededError:
            self._fail(generation, "The daily AI usage limit is reached")
            return

        references = []
        if generation.logo_file_id:
            try:
                references.append(self._logo_reference(generation.logo_file))
            except Exception:  # noqa: BLE001 - storage and image errors vary
                logger.exception("could not read cover image logo %s", generation.id)
                self._fail(generation, "Could not read the logo")
                return

        prompt = CoverImagePrompts.build(
            document_type=generation.document_type,
            title=generation.title,
            subtitle=generation.subtitle,
            organization=generation.organization,
            funding_amount_usd=generation.funding_amount_usd,
            has_logo=bool(references),
        )
        image = self._generate_or_none(prompt, references)
        if image is None:
            self._fail(generation, "OpenRouter returned no image")
            return
        # The image came back, so it was billed, whether or not it is stored.
        self._record_usage(generation, image)

        jpeg = self._jpeg_or_none(image)
        if jpeg is None:
            self._fail(generation, "Could not re-encode the image")
            return
        try:
            key = self._store(generation, jpeg)
        except Exception:  # noqa: BLE001 - storage errors vary
            logger.exception("could not store cover image %s", generation.id)
            self._fail(generation, "Could not store the image")
            return
        # A request already reported timed out stays failed.
        CoverImageGeneration.objects.filter(
            id=generation.id, status=CoverImageGeneration.Status.PROCESSING
        ).update(
            status=CoverImageGeneration.Status.COMPLETED,
            image_key=key,
            updated_date=timezone.now(),
        )

    def image_url(self, key: str) -> str:
        return self.storage.url(key)

    def public(self, generation: CoverImageGeneration) -> dict:
        """The API shape of a generation request."""
        failed = generation.status == CoverImageGeneration.Status.FAILED
        key = generation.image_key
        return {
            "id": generation.id,
            "status": generation.status,
            "image": {"key": key, "url": self.image_url(key)} if key else None,
            "error": self.GENERATION_FAILED_MESSAGE if failed else None,
        }

    @staticmethod
    def cover_logo(note: Note) -> AgentFile | None:
        """The note's cover logo, while its attachment can still be read."""
        logo = (
            NoteCoverLogo.objects.select_related("file")
            .filter(note=note, file__status=AgentFile.Status.READY)
            .first()
        )
        return logo.file if logo is not None else None

    @staticmethod
    def _readable_note(user, note_id: int) -> Note | None:
        note = (
            Note.objects.select_related("unified_document")
            .filter(id=note_id, unified_document__is_removed=False)
            .first()
        )
        return note if note is not None and note.permissions.has_user(user) else None

    def _logo_reference(self, file: AgentFile) -> str:
        """The logo as a PNG data URL, scaled down for the request.

        Read from the original upload, not its rendered page, which drops
        transparency.
        """
        data = self.private_storage.read(
            file.storage_key, max_bytes=self.LOGO_MAX_BYTES, if_match=file.etag
        )
        with Image.open(io.BytesIO(data)) as logo:
            logo = logo.convert("RGBA")
            logo.thumbnail((self.LOGO_MAX_SIDE, self.LOGO_MAX_SIDE))
            output = io.BytesIO()
            logo.save(output, format="PNG")
        encoded = base64.b64encode(output.getvalue()).decode()
        return f"data:image/png;base64,{encoded}"

    def _generate_or_none(
        self, prompt: str, references: list[str]
    ) -> GeneratedImage | None:
        try:
            return self.client.generate(
                model=self.MODEL,
                prompt=prompt,
                aspect_ratio=self.ASPECT_RATIO,
                quality=self.QUALITY,
                reference_images=references or None,
            )
        except Exception:  # noqa: BLE001 - provider errors vary
            logger.exception("cover image generation failed")
            return None

    def _record_usage(
        self, generation: CoverImageGeneration, image: GeneratedImage
    ) -> None:
        """Charge the user's daily budget what OpenRouter billed for ``image``."""
        if image.cost_microusd is None:
            logger.warning(
                "OpenRouter reported no cost for cover image generation %s",
                generation.id,
            )
        try:
            record(
                generation.created_by,
                COVER_IMAGE_FEATURE,
                "openrouter",
                self.MODEL,
                TurnUsage(
                    input_tokens=image.input_tokens,
                    output_tokens=image.output_tokens,
                    provider_cost_microusd=image.cost_microusd,
                ),
            )
        except Exception:  # noqa: BLE001 - accounting must not lose the banner
            logger.exception("could not record cover image usage for %s", generation.id)

    def _jpeg_or_none(self, image: GeneratedImage) -> bytes | None:
        """Re-encode the provider's image (often a large PNG) as a JPEG."""
        try:
            with Image.open(io.BytesIO(image.data)) as source:
                output = io.BytesIO()
                source.convert("RGB").save(
                    output, format="JPEG", quality=self.JPEG_QUALITY
                )
            return output.getvalue()
        except Exception:  # noqa: BLE001 - image decoding errors vary
            logger.exception("could not re-encode a generated cover image")
            return None

    def _store(self, generation: CoverImageGeneration, image: bytes) -> str:
        # Same layout as covers uploaded through the asset upload endpoint.
        key = f"uploads/posts/users/{generation.created_by_id}/{uuid.uuid4()}/cover.jpg"
        return self.storage.save(key, ContentFile(image))

    def _fail(self, generation: CoverImageGeneration, reason: str) -> None:
        logger.warning("cover image generation %s failed: %s", generation.id, reason)
        CoverImageGeneration.objects.filter(
            id=generation.id, status__in=self.ACTIVE_STATUSES
        ).update(
            status=CoverImageGeneration.Status.FAILED,
            error=reason,
            updated_date=timezone.now(),
        )
