from unittest import TestCase

import fitz
from django.test import SimpleTestCase, override_settings

from research_ai.services.agent_files.extraction import (
    NO_TEXT_LAYER,
    OCR_NOTE,
    PDF,
    resolve_kind,
)
from research_ai.services.agent_files.extraction_service import (
    OcrConfig,
    TextExtractionService,
)
from research_ai.services.agent_files.ocr import OcrError
from research_ai.tests.agent_files.helpers import pdf_bytes

MAX_CHARS = 10_000
SCAN = object()


def pdf_with_scans(*pages) -> bytes:
    """A PDF whose ``SCAN`` pages hold only an image; other pages hold text."""
    document = fitz.open()
    for content in pages:
        page = document.new_page()
        if content is SCAN:
            pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40), False)
            pixmap.clear_with(180)
            page.insert_image(page.rect, pixmap=pixmap)
        elif content:
            page.insert_text((72, 72), content)
    data = document.tobytes()
    document.close()
    return data


class FakeOcr:
    """Reads each page as ``Scan <n>``; ``failing`` pages raise ``OcrError``."""

    def __init__(self, failing=()):
        self.failing = set(failing)
        self.images = []

    def read_page(self, image):
        self.images.append(image)
        if image.page in self.failing:
            raise OcrError(f"page {image.page} unreadable")
        return f"Scan {image.page}"


class TextExtractionServiceTests(TestCase):
    def test_only_pages_without_a_text_layer_go_to_the_engine(self):
        # Arrange
        ocr = FakeOcr()
        service = TextExtractionService(ocr=ocr, config=OcrConfig(dpi=72))
        data = pdf_with_scans("Alpha findings", SCAN, "Gamma results")

        # Act
        extracted = service.extract(data, PDF, max_chars=MAX_CHARS)

        # Assert
        self.assertEqual(
            extracted.text,
            f"[Page 1]\nAlpha findings\n\n[Page 2]\n{OCR_NOTE}\nScan 2"
            "\n\n[Page 3]\nGamma results",
        )
        self.assertEqual(extracted.ocr_pages, (2,))
        self.assertEqual(extracted.pages_without_text, ())
        (image,) = ocr.images
        self.assertEqual((image.page, image.media_type), (2, "image/jpeg"))
        # An A4 page at the configured 72 DPI.
        self.assertEqual((image.width, image.height), (595, 842))

    def test_without_an_engine_the_pages_are_only_marked(self):
        # Arrange
        service = TextExtractionService()
        data = pdf_with_scans("Alpha findings", SCAN)

        # Act
        extracted = service.extract(data, PDF, max_chars=MAX_CHARS)

        # Assert
        self.assertEqual(
            extracted.text, f"[Page 1]\nAlpha findings\n\n[Page 2]\n{NO_TEXT_LAYER}"
        )
        self.assertEqual(extracted.pages_without_text, (2,))

    def test_pages_past_the_cap_stay_marked(self):
        # Arrange
        ocr = FakeOcr()
        service = TextExtractionService(ocr=ocr, config=OcrConfig(max_pages=2))
        data = pdf_with_scans(SCAN, SCAN, SCAN)

        # Act
        extracted = service.extract(data, PDF, max_chars=MAX_CHARS)

        # Assert
        self.assertEqual([image.page for image in ocr.images], [1, 2])
        self.assertEqual(extracted.ocr_pages, (1, 2))
        self.assertEqual(extracted.pages_without_text, (3,))

    def test_a_page_the_engine_cannot_read_stays_marked(self):
        # Arrange
        service = TextExtractionService(ocr=FakeOcr(failing={1}))
        data = pdf_with_scans(SCAN, SCAN)

        # Act
        with self.assertLogs(
            "research_ai.services.agent_files.extraction_service", "WARNING"
        ):
            extracted = service.extract(data, PDF, max_chars=MAX_CHARS)

        # Assert
        self.assertEqual(
            extracted.text,
            f"[Page 1]\n{NO_TEXT_LAYER}\n\n[Page 2]\n{OCR_NOTE}\nScan 2",
        )
        self.assertEqual(extracted.pages_without_text, (1,))

    def test_an_engine_that_keeps_failing_is_not_asked_again(self):
        # Arrange
        ocr = FakeOcr(failing={2, 3, 4, 5})
        service = TextExtractionService(ocr=ocr)
        data = pdf_with_scans("Alpha findings", SCAN, SCAN, SCAN, SCAN)

        # Act
        with self.assertLogs(
            "research_ai.services.agent_files.extraction_service", "WARNING"
        ):
            extracted = service.extract(data, PDF, max_chars=MAX_CHARS)

        # Assert
        self.assertEqual([image.page for image in ocr.images], [2, 3, 4])
        self.assertEqual(extracted.pages_without_text, (2, 3, 4, 5))

    def test_ocr_stops_when_its_time_is_up(self):
        # Arrange
        ocr = FakeOcr()
        service = TextExtractionService(ocr=ocr, config=OcrConfig(max_seconds=0))
        data = pdf_with_scans("Alpha findings", SCAN)

        # Act
        with self.assertLogs(
            "research_ai.services.agent_files.extraction_service", "WARNING"
        ):
            extracted = service.extract(data, PDF, max_chars=MAX_CHARS)

        # Assert
        self.assertEqual(ocr.images, [])
        self.assertEqual(extracted.pages_without_text, (2,))

    def test_files_with_text_never_reach_the_engine(self):
        # Arrange
        ocr = FakeOcr()
        service = TextExtractionService(ocr=ocr)

        # Act
        pdf = service.extract(pdf_bytes("Alpha findings"), PDF, max_chars=MAX_CHARS)
        text = service.extract(b"Plain notes", resolve_kind("a.txt"), max_chars=100)

        # Assert
        self.assertEqual(pdf.text, "[Page 1]\nAlpha findings")
        self.assertEqual(text.text, "Plain notes")
        self.assertEqual(ocr.images, [])


class OcrConfigTests(SimpleTestCase):
    @override_settings(RESEARCH_AI_FILE_OCR_MAX_PAGES=5, RESEARCH_AI_FILE_OCR_DPI=150)
    def test_settings_override_the_defaults(self):
        # Act
        config = TextExtractionService().config

        # Assert
        self.assertEqual((config.max_pages, config.dpi), (5, 150))
        self.assertEqual(config.max_seconds, OcrConfig().max_seconds)
