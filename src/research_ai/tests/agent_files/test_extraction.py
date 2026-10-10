import base64
import codecs
import io
import json
import pathlib
import random
import subprocess
import tempfile
from unittest import TestCase
from unittest.mock import patch

import fitz
from PIL import Image

from research_ai.services.agent_files import extraction
from research_ai.services.agent_files.extraction import (
    DOCX,
    EMBEDDED_IMAGE_NOT_SHOWN,
    IMAGE_UNREAD,
    MAX_EMBEDDED_IMAGES,
    NO_TEXT_LAYER,
    OCR_NOTE,
    PDF,
    UnreadableFileError,
    extract_text,
    prepare_image,
    render_pdf_page,
    resolve_kind,
)
from research_ai.tests.agent_files.helpers import (
    SCAN,
    docx_bytes,
    image_bytes,
    paragraph,
    pdf_bytes,
    pdf_with_scans,
    picture,
    picture_parts,
    stamped_scan,
)

TEXT = resolve_kind("notes.txt")
MAX_CHARS = 10_000
STAMP = "Downloaded from an archive on 5 March 2019"


def page_of_text() -> bytes:
    """A PDF page full of text, whose render is far larger than a blank page's."""
    document = fitz.open()
    page = document.new_page()
    page.insert_textbox(fitz.Rect(54, 54, 541, 788), "finding " * 600, fontsize=9)
    data = document.tobytes()
    document.close()
    return data


def pdf_claiming(
    count: int, *pages: str, cycle: bool = False, inline: bool = False
) -> bytes:
    """``pdf_bytes(*pages)`` with its page tree's /Count forged to ``count``.

    ``cycle`` also lists the tree's root among its own pages, which keeps MuPDF
    from correcting the count. ``inline`` writes the tree into the catalog,
    where the count cannot be lowered.
    """
    document = fitz.open(stream=pdf_bytes(*pages), filetype="pdf")
    catalog = document.pdf_catalog()
    root = int(document.xref_get_key(catalog, "Pages")[1].split()[0])
    kids = document.xref_get_key(root, "Kids")[1]
    if cycle:
        document.xref_set_key(root, "Kids", f"{kids[:-1]} {root} 0 R]")
    document.xref_set_key(root, "Count", str(count))
    if inline:
        tree = f"<</Type/Pages/Kids{kids}/Count {count}>>"
        document.xref_set_key(catalog, "Pages", tree)
    data = document.tobytes()
    document.close()
    return data


class ResolveKindTests(TestCase):
    def test_extension_decides_the_kind(self):
        # Act / Assert
        self.assertEqual(resolve_kind("Grant.PDF"), PDF)
        self.assertEqual(resolve_kind("cv.docx", "application/octet-stream"), DOCX)
        self.assertEqual(resolve_kind("notes.md").content_type, "text/markdown")
        self.assertEqual(resolve_kind("paper.tex").extractor, "text")
        self.assertEqual(resolve_kind("Figure 2.JPG").content_type, "image/jpeg")
        self.assertTrue(resolve_kind("gel.webp").is_image)
        self.assertFalse(PDF.is_image)

    def test_unsupported_extensions_are_refused_whatever_the_declared_type(self):
        # Act / Assert
        self.assertIsNone(resolve_kind("legacy.doc", "application/pdf"))
        self.assertIsNone(resolve_kind("slides.pptx"))

    def test_a_name_without_extension_falls_back_to_the_declared_type(self):
        # Act / Assert
        self.assertEqual(resolve_kind("scan", "application/pdf"), PDF)
        self.assertEqual(
            resolve_kind("readme", "text/markdown; charset=utf-8").label,
            "Markdown file",
        )
        self.assertIsNone(resolve_kind("blob", "application/octet-stream"))


class PdfExtractionTests(TestCase):
    def test_each_page_is_introduced_by_its_marker(self):
        # Arrange
        data = pdf_bytes("Alpha findings", "Beta methods")

        # Act
        extracted = extract_text(data, PDF, max_chars=MAX_CHARS)

        # Assert
        self.assertEqual(
            extracted.text, "[Page 1]\nAlpha findings\n\n[Page 2]\nBeta methods"
        )
        self.assertEqual(extracted.page_count, 2)
        self.assertFalse(extracted.truncated)

    def test_long_text_is_cut_and_flagged(self):
        # Arrange
        data = pdf_bytes("First page text", "Second page text", "Third page text")

        # Act
        extracted = extract_text(data, PDF, max_chars=30)

        # Assert
        self.assertEqual(len(extracted.text), 30)
        self.assertTrue(extracted.text.startswith("[Page 1]\nFirst page text"))
        self.assertTrue(extracted.truncated)
        self.assertEqual(extracted.page_count, 3)

    def test_a_pdf_of_blank_pages_is_refused(self):
        # Arrange
        data = pdf_bytes("", "")
        asked = []

        # Act / Assert
        with self.assertRaisesRegex(UnreadableFileError, "pages are blank"):
            extract_text(data, PDF, max_chars=MAX_CHARS)
        with self.assertRaisesRegex(UnreadableFileError, "pages are blank"):
            extract_text(data, PDF, max_chars=MAX_CHARS, recover_pages=asked.append)
        self.assertEqual(asked, [])

    def test_a_password_protected_pdf_is_refused(self):
        # Arrange
        data = pdf_bytes(
            "Secret",
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="owner",
            user_pw="user",
        )

        # Act / Assert
        with self.assertRaisesRegex(UnreadableFileError, "password-protected"):
            extract_text(data, PDF, max_chars=MAX_CHARS)

    def test_a_page_mupdf_complains_about_still_yields_its_text(self):
        # Arrange
        document = fitz.open(stream=pdf_bytes("Alpha findings"), filetype="pdf")
        xref = document[0].get_contents()[0]
        document.update_stream(xref, document.xref_stream(xref) + b"\nnot-an-operator")
        data = document.tobytes()
        document.close()

        # Act
        extracted = extract_text(data, PDF, max_chars=MAX_CHARS)

        # Assert
        self.assertEqual(extracted.text, "[Page 1]\nAlpha findings")

    def test_no_more_than_max_chars_leaves_the_parsing_process(self):
        # Arrange
        data = pdf_bytes("A single page holding more text than the cap")
        run = subprocess.run
        payloads = []

        def run_and_capture(*args, **kwargs):
            result = run(*args, **kwargs)
            payloads.append(json.loads(result.stdout))
            return result

        # Act
        with patch.object(subprocess, "run", side_effect=run_and_capture):
            extract_text(data, PDF, max_chars=20)

        # Assert
        self.assertEqual(sum(map(len, payloads[0]["pages"])), 20)
        self.assertTrue(payloads[0]["truncated"])

    def test_a_pdf_that_exceeds_the_parsing_limits_is_refused(self):
        # Arrange
        data = pdf_bytes("Alpha findings")

        # Act / Assert
        with (
            patch.object(extraction, "_CHILD_TIMEOUT_SECONDS", 0.001),
            self.assertRaisesRegex(UnreadableFileError, "too complex"),
        ):
            extract_text(data, PDF, max_chars=MAX_CHARS)

    def test_bytes_that_are_not_a_pdf_are_refused(self):
        # Act / Assert
        with self.assertRaisesRegex(UnreadableFileError, "could not be read as a PDF"):
            extract_text(b"GIF89a not a pdf", PDF, max_chars=MAX_CHARS)


class PdfPageCountTests(TestCase):
    def test_a_forged_page_count_gives_way_to_the_pages_that_exist(self):
        # Arrange
        data = pdf_claiming(2**31 - 1, "Alpha findings", "Beta methods", "Gamma")

        # Act
        extracted = extract_text(data, PDF, max_chars=MAX_CHARS)

        # Assert
        self.assertEqual(extracted.page_count, 3)
        self.assertFalse(extracted.truncated)
        self.assertTrue(extracted.text.endswith("[Page 3]\nGamma"))

    def test_pages_are_counted_by_loading_them_where_mupdf_keeps_a_forged_count(self):
        # Arrange: the text limit is met on page 2, before the tree's cycle.
        data = pdf_claiming(2500, "Alpha findings", "Beta methods", "Gamma", cycle=True)

        # Act
        extracted = extract_text(data, PDF, max_chars=20)

        # Assert
        self.assertEqual(extracted.page_count, 3)
        self.assertTrue(extracted.truncated)

    def test_a_page_past_the_real_end_of_a_forged_pdf_is_refused(self):
        # Arrange
        data = pdf_claiming(2**31 - 1, "Alpha findings", "Beta methods")

        # Act
        last = render_pdf_page(data, 2, dpi=72)

        # Assert
        self.assertEqual((last.width, last.height), (595, 842))
        with self.assertRaisesRegex(UnreadableFileError, "has no page 3"):
            render_pdf_page(data, 3)

    def test_a_forged_page_count_that_cannot_be_lowered_is_refused(self):
        # Arrange
        data = pdf_claiming(2**31 - 1, "Alpha findings", "Beta methods", inline=True)

        # Act / Assert
        with self.assertRaisesRegex(UnreadableFileError, "could not be read as a PDF"):
            extract_text(data, PDF, max_chars=MAX_CHARS)

    def test_only_pages_left_unread_flag_a_text_limit_met_at_a_pages_end(self):
        # Act
        # Run in this process: the parent's page markers would pass the limit.
        unread = extraction._pdf_pages(pdf_bytes("Alpha", "Beta", "Gamma"), 5)
        whole = extraction._pdf_pages(pdf_bytes("Alpha"), 5)

        # Assert
        self.assertEqual(unread["pages"], ["Alpha"])
        self.assertEqual((unread["page_count"], unread["truncated"]), (3, True))
        self.assertEqual((whole["page_count"], whole["truncated"]), (1, False))


class PdfPagesWithoutTextTests(TestCase):
    def test_a_scanned_page_is_marked_and_reported(self):
        # Arrange
        data = pdf_with_scans("Alpha findings", SCAN, "Gamma results")

        # Act
        extracted = extract_text(data, PDF, max_chars=MAX_CHARS)

        # Assert
        self.assertEqual(
            extracted.text,
            f"[Page 1]\nAlpha findings\n\n[Page 2]\n{NO_TEXT_LAYER}"
            "\n\n[Page 3]\nGamma results",
        )
        self.assertEqual(extracted.pages_without_text, (2,))
        self.assertEqual(extracted.ocr_pages, ())

    def test_an_empty_page_is_not_reported_as_a_scan(self):
        # Arrange
        data = pdf_with_scans("Alpha findings", "")

        # Act
        extracted = extract_text(data, PDF, max_chars=MAX_CHARS)

        # Assert
        self.assertEqual(extracted.text, "[Page 1]\nAlpha findings\n\n[Page 2]\n")
        self.assertEqual(extracted.pages_without_text, ())

    def test_a_fully_scanned_pdf_keeps_only_its_page_markers(self):
        # Arrange
        data = pdf_with_scans(SCAN, SCAN)

        # Act
        unaided = extract_text(data, PDF, max_chars=MAX_CHARS)
        unrecovered = extract_text(
            data, PDF, max_chars=MAX_CHARS, recover_pages=lambda pages: {}
        )

        # Assert
        for extracted in (unaided, unrecovered):
            self.assertEqual(
                extracted.text,
                f"[Page 1]\n{NO_TEXT_LAYER}\n\n[Page 2]\n{NO_TEXT_LAYER}",
            )
            self.assertEqual(extracted.page_count, 2)
            self.assertEqual(extracted.pages_without_text, (1, 2))
            self.assertEqual(extracted.ocr_pages, ())
            self.assertFalse(extracted.truncated)

    def test_one_scanned_page_among_blank_ones_is_enough_to_keep_a_pdf(self):
        # Arrange
        data = pdf_with_scans("", SCAN)

        # Act
        extracted = extract_text(data, PDF, max_chars=MAX_CHARS)

        # Assert
        self.assertEqual(extracted.text, f"[Page 1]\n\n\n[Page 2]\n{NO_TEXT_LAYER}")
        self.assertEqual(extracted.pages_without_text, (2,))

    def test_recovered_text_fills_only_the_pages_without_a_text_layer(self):
        # Arrange
        data = pdf_with_scans("Alpha findings", SCAN, "", SCAN)
        asked = []

        def recover(pages):
            asked.append(list(pages))
            # Page 1 has its own text; page 4 comes back blank.
            return {1: "ignored", 2: "  Scanned budget table  ", 4: "  "}

        # Act
        extracted = extract_text(data, PDF, max_chars=MAX_CHARS, recover_pages=recover)

        # Assert
        self.assertEqual(asked, [[2, 4]])
        self.assertEqual(
            extracted.text,
            "[Page 1]\nAlpha findings"
            f"\n\n[Page 2]\n{OCR_NOTE}\nScanned budget table"
            "\n\n[Page 3]\n"
            f"\n\n[Page 4]\n{NO_TEXT_LAYER}",
        )
        self.assertEqual(extracted.ocr_pages, (2,))
        self.assertEqual(extracted.pages_without_text, (4,))

    def test_a_fully_scanned_pdf_is_read_from_recovered_text(self):
        # Arrange
        data = pdf_with_scans(SCAN, SCAN)

        # Act
        extracted = extract_text(
            data,
            PDF,
            max_chars=MAX_CHARS,
            recover_pages=lambda pages: {page: f"Scan {page}" for page in pages},
        )

        # Assert
        self.assertEqual(
            extracted.text,
            f"[Page 1]\n{OCR_NOTE}\nScan 1\n\n[Page 2]\n{OCR_NOTE}\nScan 2",
        )
        self.assertEqual(extracted.ocr_pages, (1, 2))
        self.assertEqual(extracted.pages_without_text, ())

    def test_recovered_text_counts_toward_the_cap(self):
        # Arrange
        data = pdf_with_scans(SCAN)

        # Act
        extracted = extract_text(
            data, PDF, max_chars=100, recover_pages=lambda pages: {1: "word " * 200}
        )

        # Assert
        self.assertEqual(len(extracted.text), 100)
        self.assertTrue(extracted.truncated)

    def test_recovery_is_not_asked_for_when_every_page_has_text(self):
        # Arrange
        data = pdf_bytes("Alpha findings", "")
        asked = []

        # Act
        extract_text(data, PDF, max_chars=MAX_CHARS, recover_pages=asked.append)

        # Assert
        self.assertEqual(asked, [])

    def test_a_scan_under_a_stamp_keeps_the_stamp_and_is_marked(self):
        # Arrange
        data = pdf_with_scans("Alpha findings", stamped_scan(STAMP))

        # Act
        extracted = extract_text(data, PDF, max_chars=MAX_CHARS)

        # Assert
        self.assertEqual(
            extracted.text,
            f"[Page 1]\nAlpha findings\n\n[Page 2]\n{STAMP}\n{IMAGE_UNREAD}",
        )
        self.assertEqual(extracted.pages_without_text, (2,))

    def test_recovered_text_replaces_the_stamp_on_a_scan(self):
        # Arrange
        data = pdf_with_scans("Alpha findings", stamped_scan(STAMP), SCAN)
        asked = []

        def recover(pages):
            asked.append(list(pages))
            return {2: f"Scanned methods\n{STAMP}", 3: "Scanned results"}

        # Act
        extracted = extract_text(data, PDF, max_chars=MAX_CHARS, recover_pages=recover)

        # Assert
        self.assertEqual(asked, [[2, 3]])
        self.assertEqual(
            extracted.text,
            "[Page 1]\nAlpha findings"
            f"\n\n[Page 2]\n{OCR_NOTE}\nScanned methods\n{STAMP}"
            f"\n\n[Page 3]\n{OCR_NOTE}\nScanned results",
        )
        self.assertEqual(extracted.ocr_pages, (2, 3))
        self.assertEqual(extracted.pages_without_text, ())

    def test_a_page_of_text_with_an_image_is_not_taken_for_a_scan(self):
        # Arrange
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40), False)
        document = fitz.open()
        # A full page of text over a background image.
        background = document.new_page()
        background.insert_image(background.rect, pixmap=pixmap)
        background.insert_textbox(fitz.Rect(72, 72, 540, 720), "finding " * 100)
        # A caption beside a small figure.
        figure = document.new_page()
        figure.insert_image(fitz.Rect(72, 100, 272, 300), pixmap=pixmap)
        figure.insert_text((72, 72), "Figure 1: Yield by year")
        data = document.tobytes()
        document.close()
        asked = []

        # Act
        extracted = extract_text(
            data, PDF, max_chars=MAX_CHARS, recover_pages=asked.append
        )

        # Assert
        self.assertEqual(asked, [])
        self.assertNotIn(IMAGE_UNREAD, extracted.text)
        self.assertEqual(extracted.pages_without_text, ())

    def test_a_page_whose_images_cannot_be_listed_keeps_its_text(self):
        # Arrange
        data = pdf_with_scans(stamped_scan(STAMP))

        # Act
        # Run in this process: a patch does not reach the parsing child.
        with patch.object(
            fitz.Page, "get_image_info", side_effect=RuntimeError("damaged image")
        ):
            output = extraction._pdf_pages(data, MAX_CHARS)

        # Assert
        self.assertEqual(output["pages"], [STAMP])
        self.assertEqual(output["mostly_image"], [])


class PdfPageRenderingTests(TestCase):
    def test_a_page_renders_as_a_jpeg_at_the_requested_resolution(self):
        # Arrange
        data = pdf_bytes("Alpha findings", "Beta methods")

        # Act
        image = render_pdf_page(data, 2, dpi=72)

        # Assert
        self.assertEqual(image.page, 2)
        self.assertEqual(image.media_type, "image/jpeg")
        self.assertTrue(image.data.startswith(b"\xff\xd8\xff"))
        # PyMuPDF's default page is A4: 595 x 842 points.
        self.assertEqual((image.width, image.height), (595, 842))

    def test_a_page_renders_as_a_png_on_request(self):
        # Arrange
        data = pdf_bytes("Alpha findings")

        # Act
        image = render_pdf_page(data, 1, image_format="png")

        # Assert
        self.assertEqual(image.media_type, "image/png")
        self.assertTrue(image.data.startswith(b"\x89PNG"))

    def test_neither_side_exceeds_the_edge_limit(self):
        # Arrange
        data = pdf_bytes("Alpha findings")

        # Act
        image = render_pdf_page(data, 1, dpi=600, max_edge_px=1000)
        unbounded = render_pdf_page(data, 1, dpi=2000, max_edge_px=100_000)

        # Assert
        self.assertEqual(max(image.width, image.height), 1000)
        self.assertLessEqual(max(unbounded.width, unbounded.height), 4000)

    def test_a_page_within_the_byte_limit_is_left_at_full_size(self):
        # Arrange
        data = page_of_text()
        full = render_pdf_page(data, 1)

        # Act
        image = render_pdf_page(data, 1, max_bytes=len(full.data))

        # Assert
        self.assertEqual(image, full)

    def test_a_page_just_over_the_byte_limit_keeps_most_of_its_resolution(self):
        # Arrange
        data = page_of_text()
        full = render_pdf_page(data, 1)
        limit = len(full.data) * 95 // 100

        # Act
        image = render_pdf_page(data, 1, max_bytes=limit)

        # Assert
        self.assertLessEqual(len(image.data), limit)
        self.assertLess(image.width, full.width)
        self.assertGreater(image.width, 0.85 * full.width)

    def test_a_page_far_over_the_byte_limit_fits_within_a_few_renders(self):
        # Arrange
        data = page_of_text()
        limit = len(render_pdf_page(data, 1).data) // 10

        # Act
        # Run in this process: a patch does not reach the rendering child.
        with patch.object(
            fitz.Page, "get_pixmap", autospec=True, side_effect=fitz.Page.get_pixmap
        ) as render:
            output = extraction._pdf_page_image(data, 1, 150, 2000, "jpeg", limit)

        # Assert
        self.assertLessEqual(len(base64.b64decode(output["image"])), limit)
        self.assertLessEqual(render.call_count, 4)

    def test_a_page_that_cannot_fit_the_byte_limit_is_refused(self):
        # Arrange
        data = page_of_text()

        # Act / Assert
        with self.assertRaisesRegex(UnreadableFileError, "too detailed"):
            render_pdf_page(data, 1, max_bytes=500)

    def test_a_page_the_pdf_does_not_have_is_refused(self):
        # Arrange
        data = pdf_bytes("Alpha findings")

        # Act / Assert
        with self.assertRaisesRegex(UnreadableFileError, "has no page 2"):
            render_pdf_page(data, 2)

    def test_rendering_refuses_what_text_extraction_refuses(self):
        # Arrange
        locked = pdf_bytes(
            "Secret",
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="owner",
            user_pw="user",
        )

        # Act / Assert
        with self.assertRaisesRegex(UnreadableFileError, "could not be read as a PDF"):
            render_pdf_page(b"GIF89a not a pdf", 1)
        with self.assertRaisesRegex(UnreadableFileError, "password-protected"):
            render_pdf_page(locked, 1)

    def test_rendering_runs_under_the_parsing_limits(self):
        # Arrange
        data = pdf_bytes("Alpha findings")

        # Act / Assert
        with (
            patch.object(extraction, "_CHILD_TIMEOUT_SECONDS", 0.001),
            self.assertRaisesRegex(UnreadableFileError, "too complex"),
        ):
            render_pdf_page(data, 1)

    def test_rendering_stops_at_a_shorter_time_limit_when_given_one(self):
        # Arrange
        data = pdf_bytes("Alpha findings")

        # Act / Assert
        with self.assertRaisesRegex(UnreadableFileError, "too complex"):
            render_pdf_page(data, 1, timeout_seconds=0.001)

    def test_a_time_limit_cannot_extend_the_parsing_limits(self):
        # Arrange
        data = pdf_bytes("Alpha findings")

        # Act / Assert
        with (
            patch.object(extraction, "_CHILD_TIMEOUT_SECONDS", 0.001),
            self.assertRaisesRegex(UnreadableFileError, "too complex"),
        ):
            render_pdf_page(data, 1, timeout_seconds=60)

    def test_invalid_arguments_are_rejected_before_any_work(self):
        # Arrange
        data = pdf_bytes("Alpha findings")

        # Act / Assert
        with patch.object(subprocess, "run") as run:
            for arguments in (
                {"page": 0},
                {"page": 1, "dpi": 0},
                {"page": 1, "image_format": "tiff"},
            ):
                with self.assertRaises(ValueError):
                    render_pdf_page(data, **arguments)
        run.assert_not_called()


def _pixel(image, at=(0, 0)) -> tuple:
    with Image.open(io.BytesIO(image.data)) as stored:
        return stored.convert("RGB").getpixel(at)


class UploadedImageTests(TestCase):
    def _assert_color(self, pixel, expected):
        """Lossy formats shift a colour by a few levels."""
        for channel, level in zip(pixel, expected, strict=True):
            self.assertAlmostEqual(channel, level, delta=8)

    def test_an_image_becomes_a_jpeg_no_side_over_the_edge_limit(self):
        # Arrange
        data = image_bytes((400, 100))

        # Act
        image = prepare_image(data, max_edge_px=200)
        as_it_is = prepare_image(data)

        # Assert
        self.assertEqual((image.page, image.media_type), (1, "image/jpeg"))
        self.assertEqual((image.width, image.height), (200, 50))
        with Image.open(io.BytesIO(image.data)) as stored:
            self.assertEqual((stored.format, stored.size), ("JPEG", (200, 50)))
        # A small image is not enlarged.
        self.assertEqual((as_it_is.width, as_it_is.height), (400, 100))

    def test_each_supported_format_is_read_whatever_its_extension_said(self):
        for image_format in ("PNG", "JPEG", "GIF", "WEBP"):
            with self.subTest(image_format=image_format):
                # Arrange
                data = image_bytes(color=(200, 30, 30), image_format=image_format)

                # Act
                image = prepare_image(data)

                # Assert
                self._assert_color(_pixel(image), (200, 30, 30))

    def test_a_file_that_is_not_one_of_those_images_is_refused(self):
        cases = {
            "text": b"Specific aims",
            "bitmap": image_bytes(image_format="BMP"),
            "cut short": image_bytes((300, 300))[:200],
        }
        for name, data in cases.items():
            # Act / Assert
            with self.subTest(name), self.assertRaises(UnreadableFileError) as raised:
                prepare_image(data)
            self.assertIn("could not be read as an image", str(raised.exception))

    def test_a_photo_taken_sideways_is_turned_upright(self):
        # Arrange: EXIF orientation 6 asks for a quarter turn.
        exif = Image.Exif()
        exif[0x0112] = 6
        data = image_bytes((40, 20), image_format="JPEG", exif=exif)

        # Act
        image = prepare_image(data)

        # Assert
        self.assertEqual((image.width, image.height), (20, 40))

    def test_transparency_shows_as_white(self):
        # Arrange: black where it is opaque, as a figure's lines are.
        clear = image_bytes(color=(0, 0, 0, 0), mode="RGBA")
        palette = image_bytes(color=0, mode="P", image_format="GIF", transparency=0)

        for data in (clear, palette):
            # Act
            image = prepare_image(data)

            # Assert
            self._assert_color(_pixel(image), (255, 255, 255))

    def test_sixteen_bit_greys_keep_their_levels(self):
        # Arrange: mid grey, which a plain conversion to 8 bits turns white.
        data = image_bytes(color=32768, mode="I;16")

        # Act
        image = prepare_image(data)

        # Assert
        self._assert_color(_pixel(image), (127, 127, 127))

    def test_an_image_over_the_byte_limit_is_scaled_down_to_fit(self):
        # Arrange: noise, which a JPEG cannot compress away.
        noise = Image.frombytes("RGB", (600, 600), random.Random(0).randbytes(1080000))
        buffer = io.BytesIO()
        noise.save(buffer, "PNG")
        data = buffer.getvalue()
        full = prepare_image(data)
        limit = len(full.data) // 3

        # Act
        image = prepare_image(data, max_bytes=limit)

        # Assert
        self.assertLessEqual(len(image.data), limit)
        self.assertLess(image.width, full.width)
        self.assertEqual(image.width, image.height)
        with self.assertRaises(UnreadableFileError) as raised:
            prepare_image(data, max_bytes=100)
        self.assertIn("too detailed", str(raised.exception))

    def test_only_a_jpeg_may_hold_more_pixels_than_are_decoded(self):
        # Arrange: 81 megapixels; a JPEG decodes at a fraction of its size.
        png = image_bytes((9000, 9000), 0, mode="1")
        jpeg = image_bytes((9000, 9000), 128, mode="L", image_format="JPEG")

        # Act
        image = prepare_image(jpeg)
        with self.assertRaises(UnreadableFileError) as raised:
            prepare_image(png)

        # Assert
        self.assertEqual((image.width, image.height), (2000, 2000))
        self.assertIn("too large to read", str(raised.exception))


class DocxExtractionTests(TestCase):
    def test_headings_paragraphs_and_tables_become_markdown(self):
        # Arrange
        body = (
            "<w:p><w:pPr><w:pStyle w:val='Heading1'/></w:pPr>"
            "<w:r><w:t>Specific Aims</w:t></w:r></w:p>"
            + paragraph("Aim one")
            + "<w:tbl><w:tr>"
            f"<w:tc>{paragraph('Year')}</w:tc><w:tc>{paragraph('Budget')}</w:tc>"
            "</w:tr><w:tr>"
            f"<w:tc>{paragraph('1')}</w:tc><w:tc>{paragraph('$50,000')}</w:tc>"
            "</w:tr></w:tbl>"
        )

        # Act
        extracted = extract_text(docx_bytes(body), DOCX, max_chars=MAX_CHARS)

        # Assert
        self.assertEqual(
            extracted.text,
            "# Specific Aims\n\nAim one\n\n"
            "| Year | Budget |\n| --- | --- |\n| 1 | $50,000 |",
        )
        self.assertIsNone(extracted.page_count)

    def test_markdown_characters_in_the_text_are_left_as_written(self):
        # Arrange
        data = docx_bytes(paragraph("p_value for 2*3 runs"))

        # Act
        extracted = extract_text(data, DOCX, max_chars=MAX_CHARS)

        # Assert
        self.assertEqual(extracted.text, "p_value for 2*3 runs")

    def test_an_image_is_kept_as_a_jpeg_and_marked_where_it_sat(self):
        # Arrange
        body = f"<w:p><w:r><w:t>Figure 1</w:t></w:r>{picture('rId1')}</w:p>"
        body += paragraph("Results")
        parts = picture_parts({"rId1": image_bytes((400, 300))})

        # Act
        extracted = extract_text(
            docx_bytes(body, parts=parts), DOCX, max_chars=MAX_CHARS
        )

        # Assert
        self.assertEqual(extracted.text, "Figure 1 [Image 1]\n\nResults")
        (image,) = extracted.embedded_images
        self.assertEqual((image.page, image.media_type), (1, "image/jpeg"))
        with Image.open(io.BytesIO(image.data)) as kept:
            self.assertEqual((kept.format, kept.size), ("JPEG", (400, 300)))

    def test_images_are_numbered_in_order_and_one_used_twice_is_kept_once(self):
        # Arrange
        body = "".join(
            f"<w:p>{picture(relationship_id)}</w:p>"
            for relationship_id in ("rId1", "rId2", "rId1")
        )
        parts = picture_parts(
            {"rId1": image_bytes((400, 300)), "rId2": image_bytes((200, 100))}
        )

        # Act
        extracted = extract_text(
            docx_bytes(body, parts=parts), DOCX, max_chars=MAX_CHARS
        )

        # Assert
        self.assertEqual(extracted.text, "[Image 1]\n\n[Image 2]\n\n[Image 1]")
        self.assertEqual(
            [(image.page, image.width) for image in extracted.embedded_images],
            [(1, 400), (2, 200)],
        )

    def test_an_icon_is_left_out_unmarked(self):
        # Arrange
        body = f"<w:p><w:r><w:t>Contact</w:t></w:r>{picture('rId1')}</w:p>"
        parts = picture_parts({"rId1": image_bytes((24, 24))})

        # Act
        extracted = extract_text(
            docx_bytes(body, parts=parts), DOCX, max_chars=MAX_CHARS
        )

        # Assert
        self.assertEqual(extracted.text, "Contact")
        self.assertEqual(extracted.embedded_images, ())

    def test_an_image_in_a_format_that_is_not_read_is_marked_as_not_shown(self):
        # Arrange: a metafile, as a chart pasted from a spreadsheet can be.
        body = paragraph("Chart") + f"<w:p>{picture('rId1')}</w:p>"
        parts = picture_parts({"rId1": b"\x01\x00\x00\x00" + bytes(64)})

        # Act
        extracted = extract_text(
            docx_bytes(body, parts=parts), DOCX, max_chars=MAX_CHARS
        )

        # Assert
        self.assertEqual(extracted.text, f"Chart\n\n{EMBEDDED_IMAGE_NOT_SHOWN}")
        self.assertEqual(extracted.embedded_images, ())

    def test_an_image_kept_outside_the_file_is_never_fetched(self):
        # Arrange
        body = paragraph("Chart") + f"<w:p>{picture('rId1', linked=True)}</w:p>"
        with tempfile.NamedTemporaryFile(suffix=".png") as outside:
            outside.write(image_bytes((400, 300)))
            outside.flush()
            parts = picture_parts(
                {}, links={"rId1": pathlib.Path(outside.name).as_uri()}
            )

            # Act
            extracted = extract_text(
                docx_bytes(body, parts=parts), DOCX, max_chars=MAX_CHARS
            )

        # Assert
        self.assertEqual(extracted.text, f"Chart\n\n{EMBEDDED_IMAGE_NOT_SHOWN}")
        self.assertEqual(extracted.embedded_images, ())

    def test_images_past_the_limit_are_marked_as_not_shown(self):
        # Arrange
        images = {
            f"rId{number}": image_bytes((40 + number, 40))
            for number in range(1, MAX_EMBEDDED_IMAGES + 2)
        }
        body = "".join(
            f"<w:p>{picture(relationship_id)}</w:p>" for relationship_id in images
        )

        # Act
        extracted = extract_text(
            docx_bytes(body, parts=picture_parts(images)), DOCX, max_chars=MAX_CHARS
        )

        # Assert
        self.assertEqual(len(extracted.embedded_images), MAX_EMBEDDED_IMAGES)
        self.assertTrue(
            extracted.text.endswith(
                f"[Image {MAX_EMBEDDED_IMAGES}]\n\n{EMBEDDED_IMAGE_NOT_SHOWN}"
            )
        )

    def test_text_that_exactly_fits_is_not_flagged_as_cut(self):
        # Arrange
        data = docx_bytes(paragraph("Aims") + paragraph("Plan"))

        # Act
        extracted = extract_text(data, DOCX, max_chars=10)

        # Assert
        self.assertEqual(extracted.text, "Aims\n\nPlan")
        self.assertFalse(extracted.truncated)

    def test_long_text_is_cut_and_flagged(self):
        # Arrange
        data = docx_bytes(paragraph("Aims") + paragraph("Plan") + paragraph("Budget"))

        # Act
        extracted = extract_text(data, DOCX, max_chars=10)

        # Assert
        self.assertEqual(extracted.text, "Aims\n\nPlan")
        self.assertTrue(extracted.truncated)

    def test_a_document_of_empty_tables_is_refused(self):
        # Arrange
        data = docx_bytes(
            "<w:tbl><w:tr><w:tc><w:p/></w:tc><w:tc><w:p/></w:tc></w:tr></w:tbl>"
        )

        # Act / Assert
        with self.assertRaisesRegex(UnreadableFileError, "No readable text"):
            extract_text(data, DOCX, max_chars=MAX_CHARS)

    def test_external_entities_are_never_resolved(self):
        # Arrange
        doctype = '<!DOCTYPE w:document [<!ENTITY xxe SYSTEM "file:///etc/hosts">]>'
        body = paragraph("Visible") + paragraph("&xxe;")

        # Act
        extracted = extract_text(
            docx_bytes(body, doctype=doctype), DOCX, max_chars=MAX_CHARS
        )

        # Assert
        self.assertTrue(extracted.text.startswith("Visible"))
        self.assertNotIn("localhost", extracted.text)

    def test_an_entity_expansion_bomb_is_refused(self):
        # Arrange
        entities = '<!ENTITY e0 "expand">' + "".join(
            f'<!ENTITY e{level} "{f"&e{level - 1};" * 10}">' for level in range(1, 10)
        )
        data = docx_bytes(
            paragraph("&e9;"), doctype=f"<!DOCTYPE w:document [{entities}]>"
        )

        # Act / Assert
        with self.assertRaisesRegex(UnreadableFileError, "Word document"):
            extract_text(data, DOCX, max_chars=MAX_CHARS)

    def test_a_document_that_exceeds_the_parsing_limits_is_refused(self):
        # Arrange
        data = docx_bytes(paragraph("Specific Aims"))

        # Act / Assert
        with (
            patch.object(extraction, "_CHILD_TIMEOUT_SECONDS", 0.001),
            self.assertRaisesRegex(UnreadableFileError, "Word document is too complex"),
        ):
            extract_text(data, DOCX, max_chars=MAX_CHARS)

    def test_a_file_that_is_not_a_docx_is_refused(self):
        # Act / Assert
        with self.assertRaisesRegex(UnreadableFileError, "Word document"):
            extract_text(b"PK\x03\x04 truncated zip", DOCX, max_chars=MAX_CHARS)


class PlainTextExtractionTests(TestCase):
    def test_utf8_with_a_bom_and_windows_newlines(self):
        # Arrange
        data = codecs.BOM_UTF8 + "Résumé\r\nline two".encode()

        # Act
        extracted = extract_text(data, TEXT, max_chars=MAX_CHARS)

        # Assert
        self.assertEqual(extracted.text, "Résumé\nline two")

    def test_utf16_and_legacy_encodings_decode(self):
        # Act
        utf16 = extract_text("Données".encode("utf-16"), TEXT, max_chars=MAX_CHARS)
        cp1252 = extract_text("café “quoted”".encode("cp1252"), TEXT, max_chars=100)

        # Assert
        self.assertEqual(utf16.text, "Données")
        self.assertEqual(cp1252.text, "café “quoted”")

    def test_binary_and_blank_files_are_refused(self):
        # Act / Assert
        with self.assertRaisesRegex(UnreadableFileError, "plain text"):
            extract_text(b"\x89PNG\r\n\x1a\n\x00\x00", TEXT, max_chars=MAX_CHARS)
        with self.assertRaisesRegex(UnreadableFileError, "No readable text"):
            extract_text(b"  \n\t ", TEXT, max_chars=MAX_CHARS)

    def test_a_file_blank_up_to_the_cap_is_refused(self):
        # Arrange
        data = b" " * 30 + b"text past the cap"

        # Act / Assert
        with self.assertRaisesRegex(UnreadableFileError, "No readable text"):
            extract_text(data, TEXT, max_chars=20)

    def test_long_text_is_cut_and_flagged(self):
        # Act
        extracted = extract_text(b"x" * 50, TEXT, max_chars=20)

        # Assert
        self.assertEqual(extracted.text, "x" * 20)
        self.assertTrue(extracted.truncated)

    def test_text_that_fits_once_nul_characters_are_removed_is_not_flagged(self):
        # Arrange
        data = "Aims\x00\x00\x00 and plan".encode("utf-16")

        # Act
        extracted = extract_text(data, TEXT, max_chars=13)

        # Assert
        self.assertEqual(extracted.text, "Aims and plan")
        self.assertFalse(extracted.truncated)
