from unittest.mock import MagicMock, patch

from django.test import TestCase

from research_ai.services.report_generator_service import (
    generate_pdf_report,
    generate_csv_file,
    upload_report_to_storage,
)


class GeneratePdfReportTests(TestCase):
    def test_generate_pdf_returns_bytes(self):
        experts = [
            {
                "name": "Jane Doe",
                "title": "Professor",
                "affiliation": "MIT",
                "expertise": "ML",
                "email": "jane@mit.edu",
                "notes": "Notes here",
            }
        ]
        query = "Machine learning"
        config = {"expert_count": 10, "expertise_level": "all_levels"}
        pdf_bytes = generate_pdf_report(experts, query, config)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_generate_pdf_empty_experts(self):
        pdf_bytes = generate_pdf_report([], "Query", {})
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))


class GenerateCsvFileTests(TestCase):
    def test_generate_csv_returns_utf8_bytes(self):
        experts = [
            {
                "name": "Alice",
                "title": "Dr",
                "affiliation": "Stanford",
                "expertise": "NLP",
                "email": "alice@stanford.edu",
                "notes": "Some notes",
            }
        ]
        csv_bytes = generate_csv_file(experts)
        self.assertIsInstance(csv_bytes, bytes)
        content = csv_bytes.decode("utf-8")
        self.assertIn("name,title,affiliation", content)
        self.assertIn("Alice", content)

    def test_generate_csv_empty_list(self):
        csv_bytes = generate_csv_file([])
        self.assertIsInstance(csv_bytes, bytes)
        self.assertIn(b"name", csv_bytes)


class UploadReportToStorageTests(TestCase):
    @patch("research_ai.services.report_generator_service.default_storage")
    def test_upload_report_returns_url(self, mock_storage):
        mock_storage.save = MagicMock()
        mock_storage.url.return_value = (
            "https://bucket.s3.amazonaws.com/research_ai/expert-finder/123/report.pdf"
        )
        url = upload_report_to_storage(
            "123", b"pdf content", "pdf", "application/pdf"
        )
        self.assertIn("123", url)
        self.assertIn("report.pdf", url)
        mock_storage.save.assert_called_once()
