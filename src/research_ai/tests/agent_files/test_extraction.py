import codecs
from unittest import TestCase

import fitz

from research_ai.services.agent_files.extraction import (
    DOCX,
    PDF,
    UnreadableFileError,
    extract_text,
    resolve_kind,
)
from research_ai.tests.agent_files.helpers import docx_bytes, paragraph, pdf_bytes

TEXT = resolve_kind("notes.txt")
MAX_CHARS = 10_000


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

    def test_bytes_that_are_not_a_pdf_are_refused(self):
        # Act / Assert
        with self.assertRaisesRegex(UnreadableFileError, "could not be read as a PDF"):
            extract_text(b"GIF89a not a pdf", PDF, max_chars=MAX_CHARS)


class DocxExtractionTests(TestCase):
    def test_paragraphs_and_table_rows_become_lines(self):
        # Arrange
        body = (
            paragraph("Specific Aims")
            + "<w:p><w:r><w:t>Aim</w:t><w:tab/><w:t>one</w:t><w:br/>"
            "<w:t>continued</w:t></w:r></w:p>"
            "<w:tbl><w:tr>"
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
            "Specific Aims\nAim\tone\ncontinued\nYear | Budget\n1 | $50,000",
        )
        self.assertIsNone(extracted.page_count)

    def test_deleted_revisions_and_fallback_renderings_are_skipped(self):
        # Arrange
        body = (
            "<w:p><w:r><w:t>Kept</w:t></w:r>"
            "<w:del><w:r><w:delText>Removed</w:delText></w:r></w:del>"
            "<mc:AlternateContent><mc:Choice><w:r><w:t> once</w:t></w:r></mc:Choice>"
            "<mc:Fallback><w:r><w:t> twice</w:t></w:r></mc:Fallback>"
            "</mc:AlternateContent></w:p>"
        )

        # Act
        extracted = extract_text(docx_bytes(body), DOCX, max_chars=MAX_CHARS)

        # Assert
        self.assertEqual(extracted.text, "Kept once")

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

    def test_long_text_is_cut_and_flagged(self):
        # Act
        extracted = extract_text(b"x" * 50, TEXT, max_chars=20)

        # Assert
        self.assertEqual(extracted.text, "x" * 20)
        self.assertTrue(extracted.truncated)
