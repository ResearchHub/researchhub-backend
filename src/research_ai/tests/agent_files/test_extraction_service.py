import threading
import time
from unittest import TestCase

from django.test import SimpleTestCase, override_settings

from research_ai.services.agent_files.extraction import (
    DOCX,
    IMAGE_OCR_NOTE,
    NO_TEXT_LAYER,
    OCR_NOTE,
    PDF,
    UnreadableFileError,
    resolve_kind,
)
from research_ai.services.agent_files.extraction_service import (
    OcrConfig,
    TextExtractionService,
)
from research_ai.services.agent_files.ocr import OcrError
from research_ai.tests.agent_files.helpers import (
    SCAN,
    docx_bytes,
    image_bytes,
    pdf_bytes,
    pdf_with_scans,
    stamped_scan,
)

MAX_CHARS = 10_000
PNG = resolve_kind("figure.png")


class FakeOcr:
    """Reads each page as ``Scan <n>``.

    ``failing`` pages raise ``OcrError``; ``empty`` ones have no text to read.
    """

    def __init__(self, failing=(), empty=()):
        self.failing = set(failing)
        self.empty = set(empty)
        self.images = []

    def read_page(self, image):
        self.images.append(image)
        if image.page in self.failing:
            raise OcrError(f"page {image.page} unreadable")
        return "" if image.page in self.empty else f"Scan {image.page}"

    @property
    def pages(self):
        return sorted(image.page for image in self.images)


class StallingOcr(FakeOcr):
    """Reads pages at once, except ``stalled`` ones, which wait for ``release``."""

    def __init__(self, stalled):
        super().__init__()
        self.stalled = set(stalled)
        self.release = threading.Event()

    def read_page(self, image):
        if image.page in self.stalled:
            self.release.wait(timeout=30)
        return super().read_page(image)


class PairedOcr:
    """Reads a page only while another read is in flight."""

    def __init__(self):
        self.together = threading.Barrier(2, timeout=10)

    def read_page(self, image):
        try:
            self.together.wait()
        except threading.BrokenBarrierError as exc:
            raise OcrError(f"page {image.page} was read alone") from exc
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
        self.assertEqual(ocr.pages, [1, 2])
        self.assertEqual(extracted.ocr_pages, (1, 2))
        self.assertEqual(extracted.pages_without_text, (3,))

    def test_a_scan_under_a_stamp_goes_to_the_engine(self):
        # Arrange
        ocr = FakeOcr()
        service = TextExtractionService(ocr=ocr)
        data = pdf_with_scans("Alpha findings", stamped_scan("Downloaded 5 March"))

        # Act
        extracted = service.extract(data, PDF, max_chars=MAX_CHARS)

        # Assert
        self.assertEqual(
            extracted.text, f"[Page 1]\nAlpha findings\n\n[Page 2]\n{OCR_NOTE}\nScan 2"
        )
        self.assertEqual(ocr.pages, [2])

    def test_pages_are_read_several_at_a_time(self):
        # Arrange
        service = TextExtractionService(
            ocr=PairedOcr(), config=OcrConfig(concurrency=2)
        )
        data = pdf_with_scans(SCAN, SCAN, SCAN, SCAN)

        # Act
        extracted = service.extract(data, PDF, max_chars=MAX_CHARS)

        # Assert
        self.assertEqual(extracted.ocr_pages, (1, 2, 3, 4))

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
        ocr = FakeOcr(failing={2, 3, 4, 5, 6, 7})
        service = TextExtractionService(ocr=ocr, config=OcrConfig(concurrency=2))
        data = pdf_with_scans("Alpha findings", SCAN, SCAN, SCAN, SCAN, SCAN, SCAN)

        # Act
        with self.assertLogs(
            "research_ai.services.agent_files.extraction_service", "WARNING"
        ):
            extracted = service.extract(data, PDF, max_chars=MAX_CHARS)

        # Assert
        # The third failure in a row lands in the second pair; no third pair is read.
        self.assertEqual(ocr.pages, [2, 3, 4, 5])
        self.assertEqual(extracted.pages_without_text, (2, 3, 4, 5, 6, 7))

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

    def test_a_page_still_being_read_when_time_is_up_is_left_unread(self):
        # Arrange
        ocr = StallingOcr(stalled={2})
        self.addCleanup(ocr.release.set)
        service = TextExtractionService(
            ocr=ocr, config=OcrConfig(max_seconds=3, concurrency=2)
        )
        data = pdf_with_scans(SCAN, SCAN, SCAN)

        # Act
        started = time.monotonic()
        with self.assertLogs(
            "research_ai.services.agent_files.extraction_service", "WARNING"
        ):
            extracted = service.extract(data, PDF, max_chars=MAX_CHARS)
        elapsed = time.monotonic() - started

        # Assert
        self.assertEqual(extracted.ocr_pages, (1,))
        # Page 2 is abandoned mid-read and page 3 is never started.
        self.assertEqual(extracted.pages_without_text, (2, 3))
        self.assertEqual(ocr.pages, [1])
        # Well short of the 30 seconds the stalled read would hold a waiter.
        self.assertLess(elapsed, 15)

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


class UploadedImageTextTests(TestCase):
    def test_an_images_text_is_what_the_engine_reads_in_it(self):
        # Arrange
        ocr = FakeOcr()
        service = TextExtractionService(ocr=ocr, config=OcrConfig(max_edge_px=100))

        # Act
        extracted = service.extract(image_bytes((400, 200)), PNG, max_chars=MAX_CHARS)

        # Assert
        self.assertEqual(extracted.text, f"{IMAGE_OCR_NOTE}\nScan 1")
        self.assertIsNone(extracted.page_count)
        (image,) = ocr.images
        self.assertEqual(image.media_type, "image/jpeg")
        self.assertEqual((image.width, image.height), (100, 50))

    def test_an_image_with_nothing_to_read_is_kept_without_text(self):
        for ocr in (None, FakeOcr(empty={1})):
            with self.subTest(ocr=ocr):
                # Act
                extracted = TextExtractionService(ocr=ocr).extract(
                    image_bytes(), PNG, max_chars=MAX_CHARS
                )

                # Assert
                self.assertEqual(extracted.text, "")
                self.assertFalse(extracted.truncated)

    def test_an_image_the_engine_does_not_read_in_time_is_kept_without_text(self):
        stalling = StallingOcr(stalled={1})
        self.addCleanup(stalling.release.set)
        for ocr in (FakeOcr(failing={1}), stalling):
            with self.subTest(ocr=type(ocr).__name__):
                # Arrange
                service = TextExtractionService(
                    ocr=ocr, config=OcrConfig(max_seconds=1)
                )

                # Act
                started = time.monotonic()
                with self.assertLogs(
                    "research_ai.services.agent_files.extraction_service", "WARNING"
                ):
                    extracted = service.extract(image_bytes(), PNG, max_chars=MAX_CHARS)
                elapsed = time.monotonic() - started

                # Assert
                self.assertEqual(extracted.text, "")
                # Well short of the 30 seconds the stalled read would hold a waiter.
                self.assertLess(elapsed, 15)

    def test_a_file_that_is_not_an_image_is_refused_without_an_engine(self):
        # Act / Assert
        with self.assertRaises(UnreadableFileError):
            TextExtractionService().extract(b"Aims", PNG, max_chars=MAX_CHARS)


class FullyScannedPdfTests(TestCase):
    """A PDF with no text layer is kept: a model can still look at its pages."""

    MARKERS = f"[Page 1]\n{NO_TEXT_LAYER}\n\n[Page 2]\n{NO_TEXT_LAYER}"

    def test_it_is_kept_without_an_engine(self):
        # Arrange
        service = TextExtractionService()
        data = pdf_with_scans(SCAN, SCAN)

        # Act
        extracted = service.extract(data, PDF, max_chars=MAX_CHARS)

        # Assert
        self.assertEqual(extracted.text, self.MARKERS)
        self.assertEqual(extracted.page_count, 2)
        self.assertEqual(extracted.pages_without_text, (1, 2))

    def test_it_is_kept_when_the_engine_finds_no_text(self):
        # Arrange: an engine reads nothing on a page that is only a figure.
        ocr = FakeOcr(empty={1, 2})
        service = TextExtractionService(ocr=ocr)
        data = pdf_with_scans(SCAN, SCAN)

        # Act
        extracted = service.extract(data, PDF, max_chars=MAX_CHARS)

        # Assert
        self.assertEqual(ocr.pages, [1, 2])
        self.assertEqual(extracted.text, self.MARKERS)
        self.assertEqual(extracted.pages_without_text, (1, 2))
        self.assertEqual(extracted.ocr_pages, ())

    def test_it_is_kept_when_the_engine_is_down(self):
        # Arrange
        service = TextExtractionService(ocr=FakeOcr(failing={1, 2}))
        data = pdf_with_scans(SCAN, SCAN)

        # Act
        with self.assertLogs(
            "research_ai.services.agent_files.extraction_service", "WARNING"
        ):
            extracted = service.extract(data, PDF, max_chars=MAX_CHARS)

        # Assert
        self.assertEqual(extracted.text, self.MARKERS)
        self.assertEqual(extracted.pages_without_text, (1, 2))

    def test_the_pages_the_engine_reads_replace_their_markers(self):
        # Arrange
        service = TextExtractionService(ocr=FakeOcr(empty={2}))
        data = pdf_with_scans(SCAN, SCAN, SCAN)

        # Act
        extracted = service.extract(data, PDF, max_chars=MAX_CHARS)

        # Assert
        self.assertEqual(
            extracted.text,
            f"[Page 1]\n{OCR_NOTE}\nScan 1\n\n[Page 2]\n{NO_TEXT_LAYER}"
            f"\n\n[Page 3]\n{OCR_NOTE}\nScan 3",
        )
        self.assertEqual(extracted.ocr_pages, (1, 3))
        self.assertEqual(extracted.pages_without_text, (2,))

    def test_a_pdf_of_blank_pages_is_still_refused(self):
        # Arrange
        ocr = FakeOcr()
        service = TextExtractionService(ocr=ocr)
        data = pdf_bytes("", "")

        # Act / Assert
        with self.assertRaisesRegex(UnreadableFileError, "pages are blank"):
            service.extract(data, PDF, max_chars=MAX_CHARS)
        self.assertEqual(ocr.images, [])

    def test_a_word_file_without_text_is_still_refused(self):
        # Arrange
        ocr = FakeOcr()
        service = TextExtractionService(ocr=ocr)
        data = docx_bytes("<w:tbl><w:tr><w:tc><w:p/></w:tc></w:tr></w:tbl>")

        # Act / Assert
        with self.assertRaisesRegex(UnreadableFileError, "No readable text"):
            service.extract(data, DOCX, max_chars=MAX_CHARS)
        self.assertEqual(ocr.images, [])


class OcrConfigTests(SimpleTestCase):
    @override_settings(RESEARCH_AI_FILE_OCR_MAX_PAGES=5, RESEARCH_AI_FILE_OCR_DPI=150)
    def test_settings_override_the_defaults(self):
        # Act
        config = TextExtractionService().config

        # Assert
        self.assertEqual((config.max_pages, config.dpi), (5, 150))
        self.assertEqual(config.max_seconds, OcrConfig().max_seconds)
