"""Text extraction with an OCR fallback for PDF pages that have no text layer."""

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial

from django.conf import settings

from research_ai.services.agent_files.extraction import (
    PDF,
    ExtractedText,
    FileKind,
    UnreadableFileError,
    extract_text,
    render_pdf_page,
)
from research_ai.services.agent_files.ocr import OcrError, PageOcr

logger = logging.getLogger(__name__)

_SETTING_OVERRIDES = {
    "max_pages": "RESEARCH_AI_FILE_OCR_MAX_PAGES",
    "max_seconds": "RESEARCH_AI_FILE_OCR_MAX_SECONDS",
    "dpi": "RESEARCH_AI_FILE_OCR_DPI",
    "max_edge_px": "RESEARCH_AI_FILE_OCR_MAX_EDGE_PX",
}
# An engine failing this many pages in a row is down, not unlucky.
_MAX_CONSECUTIVE_FAILURES = 3


@dataclass(frozen=True)
class OcrConfig:
    # Pages read per file; the rest stay marked as having no text layer.
    max_pages: int = 50

    # Wall time for one file's OCR, so a slow engine cannot stall processing.
    max_seconds: int = 120

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
    """Extracts a file's text, reading PDF pages without a text layer by OCR.

    ``ocr`` is the engine; without one those pages are only marked.
    """

    def __init__(self, *, ocr: PageOcr | None = None, config: OcrConfig | None = None):
        self.ocr = ocr
        self._config = config

    @property
    def config(self) -> OcrConfig:
        return self._config or OcrConfig.from_settings()

    def extract(self, data: bytes, kind: FileKind, *, max_chars: int) -> ExtractedText:
        """Text of the file, cut at ``max_chars``. Raises ``UnreadableFileError``."""
        ocr = self.ocr is not None and kind == PDF
        return extract_text(
            data,
            kind,
            max_chars=max_chars,
            recover_pages=partial(self._ocr_pages, data) if ocr else None,
        )

    def _ocr_pages(self, data: bytes, pages: Sequence[int]) -> dict[int, str]:
        config = self.config
        deadline = time.monotonic() + config.max_seconds
        texts: dict[int, str] = {}
        failures = 0
        for page in pages[: config.max_pages]:
            if time.monotonic() >= deadline:
                logger.warning("OCR stopped at page %d: out of time", page)
                break
            try:
                image = render_pdf_page(
                    data, page, dpi=config.dpi, max_edge_px=config.max_edge_px
                )
                texts[page] = self.ocr.read_page(image)
                failures = 0
            except (OcrError, UnreadableFileError):
                logger.warning("OCR failed on page %d", page, exc_info=True)
                failures += 1
                if failures >= _MAX_CONSECUTIVE_FAILURES:
                    break
        return texts
