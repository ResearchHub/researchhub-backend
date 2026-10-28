"""Generate a cover banner for a proposal or RFP through OpenRouter.

``start`` records a request and queues it; a worker calls ``run``, which asks
OpenRouter for one banner and stores it, as a JPEG, in the default storage
under the same key layout as user-uploaded post covers. The client polls the
request until it completes, shows the banner, and sends its key as the post's
``image``.
"""

import io
import logging
import uuid
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone
from PIL import Image

from research_ai.models import CoverImageGeneration
from research_ai.prompts.cover_image_prompts import CoverImagePrompts
from research_ai.services.agent.types import TurnUsage
from research_ai.services.openrouter_image_client import (
    GeneratedImage,
    OpenRouterImageClient,
)
from research_ai.services.usage_budget import check_spend_admission, record
from research_ai.services.usage_budget.config import COVER_IMAGE_FEATURE

logger = logging.getLogger(__name__)


class CoverImageGenerationEnqueueError(RuntimeError):
    """The request was recorded but could not be queued; it is marked failed."""


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

    ACTIVE_STATUSES = (
        CoverImageGeneration.Status.PENDING,
        CoverImageGeneration.Status.PROCESSING,
    )
    # Generating takes under a minute; a request still active well past that
    # lost its worker, and is reported failed so the client stops waiting.
    STALE_AFTER = timedelta(minutes=10)
    # The worker's ceiling, above the image call's own client timeout.
    TIME_LIMIT_SECONDS = 6 * 60

    GENERATION_FAILED_MESSAGE = "Could not generate a cover image. Please try again."

    def __init__(
        self,
        client: OpenRouterImageClient | None = None,
        storage=None,
        enqueue: Callable[[int], None] | None = None,
    ):
        self.client = client if client is not None else self._default_client()
        self.storage = storage if storage is not None else default_storage
        self.enqueue = (
            enqueue if enqueue is not None else _enqueue_cover_image_generation
        )

    @staticmethod
    def _default_client() -> OpenRouterImageClient | None:
        api_key = getattr(settings, "OPENROUTER_API_KEY", "") or ""
        return OpenRouterImageClient(api_key) if api_key else None

    def start(
        self,
        *,
        user,
        document_type: str,
        title: str,
        subtitle: str = "",
        organization: str = "",
        funding_amount_usd: Decimal | None = None,
    ) -> CoverImageGeneration:
        """Record a generation request and queue it for a worker.

        Raises ``UsageLimitExceededError`` once the user's daily AI budget is
        spent; generating spends it, in dollars only.
        """
        check_spend_admission(user)

        generation = CoverImageGeneration.objects.create(
            created_by=user,
            document_type=document_type,
            title=title,
            subtitle=subtitle,
            organization=organization,
            funding_amount_usd=funding_amount_usd,
        )
        try:
            self.enqueue(generation.id)
        except Exception as error:  # noqa: BLE001 - broker clients vary
            logger.exception("could not queue cover image generation %s", generation.id)
            self._fail(generation, "Could not queue cover image generation")
            raise CoverImageGenerationEnqueueError(str(error)) from error
        return generation

    def get_for_user(self, user, generation_id: int) -> CoverImageGeneration | None:
        """The user's request, with one whose worker was lost marked failed."""
        generation = CoverImageGeneration.objects.filter(
            id=generation_id, created_by=user
        ).first()
        if (
            generation is not None
            and generation.status in self.ACTIVE_STATUSES
            and generation.created_date < timezone.now() - self.STALE_AFTER
        ):
            self._fail(generation, "Cover image generation timed out")
            generation.refresh_from_db()
        return generation

    def run(self, generation_id: int) -> None:
        """Generate and store the banner for a queued request."""
        claimed = CoverImageGeneration.objects.filter(
            id=generation_id, status=CoverImageGeneration.Status.PENDING
        ).update(status=CoverImageGeneration.Status.PROCESSING)
        if not claimed:
            return
        generation = CoverImageGeneration.objects.get(id=generation_id)
        # The key is set on the workers, not the API servers that queue this.
        if self.client is None:
            self._fail(generation, "OpenRouter is not configured")
            return

        prompt = CoverImagePrompts.build(
            document_type=generation.document_type,
            title=generation.title,
            subtitle=generation.subtitle,
            organization=generation.organization,
            funding_amount_usd=generation.funding_amount_usd,
        )
        image = self._generate_or_none(prompt)
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
        CoverImageGeneration.objects.filter(id=generation.id).update(
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

    def _generate_or_none(self, prompt: str) -> GeneratedImage | None:
        try:
            return self.client.generate(
                model=self.MODEL,
                prompt=prompt,
                aspect_ratio=self.ASPECT_RATIO,
                quality=self.QUALITY,
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
