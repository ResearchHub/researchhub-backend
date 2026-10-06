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
    "inline_max_chars_per_conversation": (
        "RESEARCH_AI_FILE_INLINE_MAX_CHARS_PER_CONVERSATION"
    ),
    "page_images_max_per_conversation": (
        "RESEARCH_AI_FILE_PAGE_IMAGES_MAX_PER_CONVERSATION"
    ),
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
    # The model takes images, but the conversation has no room left for any.
    NO_ROOM = "no_room"


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
class ConversationUsage:
    """What a conversation's context already carries, replayed on every call."""

    inline_chars: int = 0
    page_images: int = 0


@dataclass(frozen=True)
class DeliveryConfig:
    # About 15K tokens, what two or three read calls would pull anyway; longer
    # files are read through tools.
    inline_max_chars: int = 60_000

    # Inline text across one message's files; the rest fall back to tools.
    inline_max_chars_per_message: int = 120_000

    # A letter page costs about 2,700 tokens at 150 DPI, replayed on every later
    # call; the text is sent as well, so longer PDFs get pages on request.
    page_images_max_pages: int = 10

    # Pages attached across one message's files; the rest are on request. Ten
    # pages of 500 KB take half the smallest per-request image budget (10 MB).
    page_images_max_per_message: int = 10

    # Inline text across a conversation, about 60K tokens; later files go
    # behind the tools.
    inline_max_chars_per_conversation: int = 240_000

    # Pages attached or shown on request across a conversation. Twenty pages of
    # 500 KB fill the smallest per-request image budget (10 MB).
    page_images_max_per_conversation: int = 20

    def page_images_left(self, used: ConversationUsage) -> int:
        """How many more page images a conversation that carries ``used`` takes."""
        return max(0, self.page_images_max_per_conversation - used.page_images)

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
    used: ConversationUsage | None = None,
) -> list[Delivery]:
    """One ``Delivery`` per document sent with a message, in the order given.

    ``vision`` is whether the conversation's model accepts images; ``used`` is
    what the conversation already carries. Earlier documents claim first.
    """
    config = config or DeliveryConfig.from_settings()
    used = used or ConversationUsage()
    inline_room = min(
        config.inline_max_chars_per_message,
        config.inline_max_chars_per_conversation - used.inline_chars,
    )
    images_left = config.page_images_left(used)
    image_room = min(config.page_images_max_per_message, images_left)
    planned = []
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
                images_left -= pages
        planned.append((text, page_images))
    # A page can be asked for only while room is left after the attached pages.
    on_request = PageImages.ON_REQUEST if images_left else PageImages.NO_ROOM
    return [
        Delivery(
            text=text,
            page_images=(
                on_request if page_images == PageImages.ON_REQUEST else page_images
            ),
        )
        for text, page_images in planned
    ]
