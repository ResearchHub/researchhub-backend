"""How attached files reach the model: inline text, tools, images.

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
    "page_images_max_attached_per_conversation": (
        "RESEARCH_AI_FILE_PAGE_IMAGES_MAX_ATTACHED_PER_CONVERSATION"
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
    # Every page, or an uploaded image itself, is sent with the message.
    ATTACHED = "attached"
    # The model is shown the pages, or the image, it asks a tool for.
    ON_REQUEST = "on_request"
    # The model takes images, but the conversation has no room left for any.
    NO_ROOM = "no_room"


@dataclass(frozen=True)
class Document:
    text_chars: int
    # ``None`` for formats without pages (Word, text, images).
    page_count: int | None = None
    # An image the user uploaded, shown as it is: one image.
    image: bool = False


@dataclass(frozen=True)
class Delivery:
    text: TextDelivery
    page_images: PageImages


@dataclass(frozen=True)
class ConversationUsage:
    """What a conversation's context already carries, replayed on every call."""

    inline_chars: int = 0
    # Pages and uploaded images sent with messages, and those the page tool showed.
    attached_page_images: int = 0
    requested_page_images: int = 0

    @property
    def page_images(self) -> int:
        return self.attached_page_images + self.requested_page_images


@dataclass(frozen=True)
class DeliveryConfig:
    # Token figures here run from 4 characters a token to Claude's 3.1.

    # Holds a 12-15 page proposal narrative (53-87K characters), which costs
    # more read through tools: the same history plus three calls. 25-32K tokens.
    inline_max_chars: int = 100_000

    # Inline text across one message's files, 38-48K tokens; the rest fall back
    # to tools.
    inline_max_chars_per_message: int = 150_000

    # A letter page costs about 2,700 tokens at 150 DPI, replayed on every later
    # call; the text is sent as well, so longer PDFs get pages on request.
    page_images_max_pages: int = 10

    # Pages and uploaded images attached across one message's files; the rest
    # are on request. Ten of 500 KB take half the smallest per-request image
    # budget (10 MB).
    page_images_max_per_message: int = 10

    # Inline text across a conversation, 60-77K tokens; later files go behind
    # the tools.
    inline_max_chars_per_conversation: int = 240_000

    # Pages attached with messages across a conversation; the rest of its
    # images are kept for uploaded images and the pages the model asks to see.
    page_images_max_attached_per_conversation: int = 10

    # Pages and uploaded images, attached or shown on request, across a
    # conversation. Twenty of 500 KB fill the smallest per-request image budget
    # (10 MB).
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
    message_left = config.page_images_max_per_message
    attached_left = (
        config.page_images_max_attached_per_conversation - used.attached_page_images
    )
    planned = []
    for document in documents:
        text = TextDelivery.TOOLS
        if document.text_chars <= min(config.inline_max_chars, inline_room):
            text = TextDelivery.INLINE
            inline_room -= document.text_chars
        page_images = PageImages.NONE
        pages = 1 if document.image else document.page_count or 0
        if vision and pages:
            page_images = PageImages.ON_REQUEST
            room = min(message_left, images_left)
            # The attached share keeps room for what is asked for later; the
            # user asks for an image to be seen by sending it.
            if not document.image:
                room = min(room, attached_left, config.page_images_max_pages)
            if pages <= room:
                page_images = PageImages.ATTACHED
                message_left -= pages
                attached_left -= pages
                images_left -= pages
        planned.append((text, page_images))
    # A file past what is attached is on request while the conversation has
    # room, counting what is attached here.
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
