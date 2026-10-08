"""Text extraction, with OCR for uploaded images and PDF pages that are scans.

A Word document's images come out with its text, sized as page images are.
"""

import logging
import time
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from functools import partial

from django.conf import settings

from research_ai.services.agent_files.extraction import (
    IMAGE_OCR_NOTE,
    PDF,
    ExtractedText,
    FileKind,
    PageImage,
    UnreadableFileError,
    extract_text,
    prepare_image,
    render_pdf_page,
)
from research_ai.services.agent_files.ocr import OcrError, PageOcr
from research_ai.services.agent_files.page_images import PageRenderConfig

logger = logging.getLogger(__name__)

_SETTING_OVERRIDES = {
    "max_pages": "RESEARCH_AI_FILE_OCR_MAX_PAGES",
    "max_seconds": "RESEARCH_AI_FILE_OCR_MAX_SECONDS",
    "dpi": "RESEARCH_AI_FILE_OCR_DPI",
    "max_edge_px": "RESEARCH_AI_FILE_OCR_MAX_EDGE_PX",
    "concurrency": "RESEARCH_AI_FILE_OCR_CONCURRENCY",
}
# An engine failing this many pages in a row is down, not unlucky.
_MAX_CONSECUTIVE_FAILURES = 3


@dataclass(frozen=True)
class OcrConfig:
    # Pages read per file; the rest stay marked as unread.
    max_pages: int = 50

    # Wall time for one file's OCR; a page still being read then is left unread.
    max_seconds: int = 120

    # Pages read at once; a dense page takes an engine about two seconds.
    concurrency: int = 4

    dpi: int = 200

    max_edge_px: int = 2400

    @classmethod
    def from_settings(cls) -> "OcrConfig":
        defaults = cls()
        return cls(
            **{
                field: getattr(settings, setting, getattr(defaults, field))
                for field, setting in _SETTING_OVERRIDES.items()
            }
        )


class TextExtractionService:
    """Extracts a file's text, reading by OCR images and the PDF pages that are scans.

    ``ocr`` is the engine; without one those pages are only marked and an
    image has no text. ``image_config`` sizes the images kept from a Word
    document.
    """

    def __init__(
        self,
        *,
        ocr: PageOcr | None = None,
        config: OcrConfig | None = None,
        image_config: PageRenderConfig | None = None,
    ):
        self.ocr = ocr
        self._config = config
        self._image_config = image_config

    @property
    def config(self) -> OcrConfig:
        return self._config or OcrConfig.from_settings()

    @property
    def image_config(self) -> PageRenderConfig:
        return self._image_config or PageRenderConfig.from_settings()

    def extract(self, data: bytes, kind: FileKind, *, max_chars: int) -> ExtractedText:
        """Text of the file, cut at ``max_chars``. Raises ``UnreadableFileError``."""
        if kind.is_image:
            return self._image_text(data, max_chars)
        ocr = self.ocr is not None and kind == PDF
        images = self.image_config
        return extract_text(
            data,
            kind,
            max_chars=max_chars,
            recover_pages=partial(self._ocr_pages, data) if ocr else None,
            image_max_edge_px=images.max_edge_px,
            image_max_bytes=images.max_bytes,
        )

    def _image_text(self, data: bytes, max_chars: int) -> ExtractedText:
        """What OCR reads in an image; no text is fine, the image itself is shown."""
        config = self.config
        # Decoding is also what refuses a file that is not an image.
        image = prepare_image(data, max_edge_px=config.max_edge_px)
        text = ""
        if self.ocr is not None:
            text = self._read_image(image, config.max_seconds)
        # Postgres text columns cannot hold NUL.
        text = text.replace("\x00", "").strip()
        if text:
            text = f"{IMAGE_OCR_NOTE}\n{text}"
        return ExtractedText(
            text=text[:max_chars], page_count=None, truncated=len(text) > max_chars
        )

    def _read_image(self, image: PageImage, max_seconds: float) -> str:
        """The image's text; empty when the engine fails or outlasts its time."""
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            return executor.submit(self.ocr.read_page, image).result(max_seconds)
        except (OcrError, TimeoutError):
            logger.warning("OCR failed on an image", exc_info=True)
            return ""
        finally:
            # A read still running at the deadline is left behind, not waited for.
            executor.shutdown(wait=False, cancel_futures=True)

    def _ocr_pages(self, data: bytes, pages: Sequence[int]) -> dict[int, str]:
        config = self.config
        deadline = time.monotonic() + config.max_seconds
        pages = pages[: config.max_pages]
        batch_size = max(1, config.concurrency)
        read_page = partial(self._ocr_page, data, config, deadline)
        texts: dict[int, str] = {}
        failures = 0
        executor = ThreadPoolExecutor(max_workers=batch_size)
        try:
            # The failure limit is checked between batches.
            for start in range(0, len(pages), batch_size):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    logger.warning("OCR stopped at page %d: out of time", pages[start])
                    break
                batch = pages[start : start + batch_size]
                reads = [executor.submit(read_page, page) for page in batch]
                wait(reads, timeout=remaining)
                for page, read in zip(batch, reads):
                    text = _text_if_done(read, page)
                    if text is None:
                        failures += 1
                    else:
                        texts[page] = text
                        failures = 0
                if failures >= _MAX_CONSECUTIVE_FAILURES:
                    break
        finally:
            # A read still running at the deadline is left behind, not waited for.
            executor.shutdown(wait=False, cancel_futures=True)
        return texts

    def _ocr_page(
        self, data: bytes, config: OcrConfig, deadline: float, page: int
    ) -> str | None:
        """The page's text; ``None`` when it could not be rendered or read."""
        try:
            image = render_pdf_page(
                data,
                page,
                dpi=config.dpi,
                max_edge_px=config.max_edge_px,
                timeout_seconds=deadline - time.monotonic(),
            )
            return self.ocr.read_page(image)
        except (OcrError, UnreadableFileError):
            logger.warning("OCR failed on page %d", page, exc_info=True)
            return None


def _text_if_done(read: Future, page: int) -> str | None:
    if read.done():
        return read.result()
    logger.warning("OCR left page %d unread: out of time", page)
    return None
