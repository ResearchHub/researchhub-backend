import codecs
import json
import subprocess
from unittest import TestCase
from unittest.mock import patch

import fitz

from research_ai.services.agent_files import extraction
from research_ai.services.agent_files.extraction import (
    DOCX,
    IMAGE_UNREAD,
    NO_TEXT_LAYER,
    OCR_NOTE,
    PDF,
    UnreadableFileError,
    extract_text,
    render_pdf_page,
    resolve_kind,
)
from research_ai.tests.agent_files.helpers import (
    SCAN,
    docx_bytes,
    paragraph,
    pdf_bytes,
    pdf_with_scans,
    stamped_scan,
)

DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006"
RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_NS = "http://schemas.openxmlformats.org/package/2006"

TEXT = resolve_kind("notes.txt")
MAX_CHARS = 10_000
STAMP = "Downloaded from an archive on 5 March 2019"


class ResolveKindTests(TestCase):
    def test_extension_decides_the_kind(self):
        # Act / Assert
        self.assertEqual(resolve_kind("Grant.PDF"), PDF)
        self.assertEqual(resolve_kind("cv.docx", "application/octet-stream"), DOCX)
        self.assertEqual(resolve_kind("notes.md").content_type, "text/markdown")
        self.assertEqual(resolve_kind("paper.tex").extractor, "text")

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

    def test_a_pdf_without_a_text_layer_is_reported_as_a_scan(self):
        # Arrange
        data = pdf_bytes("", "")

        # Act / Assert
        with self.assertRaisesRegex(UnreadableFileError, "no selectable text"):
            extract_text(data, PDF, max_chars=MAX_CHARS)

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

    def test_a_fully_scanned_pdf_is_still_refused_without_recovered_text(self):
        # Arrange
        data = pdf_with_scans(SCAN, SCAN)

        # Act / Assert
        with self.assertRaisesRegex(UnreadableFileError, "no selectable text"):
            extract_text(data, PDF, max_chars=MAX_CHARS)
        with self.assertRaisesRegex(UnreadableFileError, "no selectable text"):
            extract_text(data, PDF, max_chars=MAX_CHARS, recover_pages=lambda pages: {})

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

    def test_a_page_is_scaled_down_until_it_fits_the_byte_limit(self):
        # Arrange
        data = pdf_bytes("Alpha findings " * 5)
        full = render_pdf_page(data, 1)

        # Act
        image = render_pdf_page(data, 1, max_bytes=len(full.data) // 3)

        # Assert
        self.assertLessEqual(len(image.data), len(full.data) // 3)
        self.assertLess(image.width, full.width)

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

    def test_images_are_left_out(self):
        # Arrange
        body = (
            "<w:p><w:r><w:t>Figure 1</w:t></w:r><w:r><w:drawing>"
            f"<wp:inline xmlns:wp='{DRAWING_NS}/wordprocessingDrawing'>"
            f"<a:graphic xmlns:a='{DRAWING_NS}/main'><a:graphicData>"
            f"<pic:pic xmlns:pic='{DRAWING_NS}/picture'><pic:blipFill>"
            f"<a:blip xmlns:r='{RELATIONSHIPS_NS}' r:embed='rId1'/>"
            "</pic:blipFill></pic:pic></a:graphicData></a:graphic></wp:inline>"
            "</w:drawing></w:r></w:p>"
        )
        relationships = (
            f"<Relationships xmlns='{PACKAGE_NS}/relationships'>"
            f"<Relationship Id='rId1' Type='{RELATIONSHIPS_NS}/image' "
            "Target='media/image1.png'/></Relationships>"
        )
        parts = {
            "word/_rels/document.xml.rels": relationships,
            "word/media/image1.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,
        }

        # Act
        extracted = extract_text(
            docx_bytes(body, parts=parts), DOCX, max_chars=MAX_CHARS
        )

        # Assert
        self.assertEqual(extracted.text, "Figure 1")

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
