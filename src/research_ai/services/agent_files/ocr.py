"""The OCR engine interface for PDF pages that have no text layer."""

from typing import Protocol

from research_ai.services.agent_files.extraction import PageImage


class OcrError(Exception):
    """The engine could not read a page; the page stays marked as unread."""


class PageOcr(Protocol):
    """One OCR engine. Adapters wrap their own failures in ``OcrError``."""

    def read_page(self, image: PageImage) -> str:
        """The text on one rendered page, in reading order; empty if none."""
