"""How attached documents reach the model: inline text, tools, page images.

Every threshold is overridable via a ``RESEARCH_AI_FILE_*`` setting, read at
call time so per-test ``override_settings`` applies.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from django.conf import settings

_SETTING_OVERRIDES = {
    "inline_max_chars": "RESEARCH_AI_FILE_INLINE_MAX_CHARS",
    "inline_max_chars_per_message": "RESEARCH_AI_FILE_INLINE_MAX_CHARS_PER_MESSAGE",
    "page_images_max_pages": "RESEARCH_AI_FILE_PAGE_IMAGES_MAX_PAGES",
    "page_images_max_per_message": "RESEARCH_AI_FILE_PAGE_IMAGES_MAX_PER_MESSAGE",
}


class TextDelivery(StrEnum):
    # The whole text goes in the user message.
    INLINE = "inline"
    # The model reads and searches the text through tools.
    TOOLS = "tools"


class PageImages(StrEnum):
    NONE = "none"
    # Every page is sent as an image with the message.
    ATTACHED = "attached"
    # The model is shown the pages it asks a tool for.
    ON_REQUEST = "on_request"


@dataclass(frozen=True)
class Document:
    text_chars: int
    # ``None`` for formats without pages (Word, text).
    page_count: int | None = None


@dataclass(frozen=True)
class Delivery:
    text: TextDelivery
    page_images: PageImages


@dataclass(frozen=True)
class DeliveryConfig:
    # About 15K tokens: longer files are read through tools.
    inline_max_chars: int = 60_000

    # Inline text across one message's files; the rest fall back to tools.
    inline_max_chars_per_message: int = 120_000

    # A letter page costs about 2,700 tokens at 150 DPI, 1,240 at 100 DPI.
    page_images_max_pages: int = 20

    # Pages attached across one message's files; the rest are on request.
    page_images_max_per_message: int = 20

    @classmethod
    def from_settings(cls) -> "DeliveryConfig":
        defaults = cls()
        return cls(
            **{
                field: getattr(settings, setting, getattr(defaults, field))
                for field, setting in _SETTING_OVERRIDES.items()
            }
        )


def plan_delivery(
    documents: Sequence[Document],
    *,
    vision: bool,
    config: DeliveryConfig | None = None,
) -> list[Delivery]:
    """One ``Delivery`` per document sent with a message, in the order given.

    ``vision`` is whether the conversation's model accepts images. Earlier
    documents claim the message's inline and image budgets first.
    """
    config = config or DeliveryConfig.from_settings()
    inline_room = config.inline_max_chars_per_message
    image_room = config.page_images_max_per_message
    deliveries = []
    for document in documents:
        text = TextDelivery.TOOLS
        if document.text_chars <= min(config.inline_max_chars, inline_room):
            text = TextDelivery.INLINE
            inline_room -= document.text_chars
        page_images = PageImages.NONE
        pages = document.page_count or 0
        if vision and pages:
            page_images = PageImages.ON_REQUEST
            if pages <= min(config.page_images_max_pages, image_room):
                page_images = PageImages.ATTACHED
                image_room -= pages
        deliveries.append(Delivery(text=text, page_images=page_images))
    return deliveries
