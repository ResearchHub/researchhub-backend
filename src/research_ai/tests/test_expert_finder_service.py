from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from research_ai.constants import ExpertiseLevel, Region
from research_ai.models import Expert, ExpertSearch, SearchExpert
from research_ai.services.expert_finder_service import (
    PDF_TOO_LARGE_MESSAGE,
    _extract_text_from_pdf_bytes,
    _get_paper_pdf_bytes,
    get_document_content,
    run_expert_finder_search,
)
from user.tests.helpers import create_random_authenticated_user


class GetDocumentContentTests(TestCase):
    def test_paper_abstract_returns_abstract(self):
        from researchhub_document.related_models.constants.document_type import PAPER

        paper = MagicMock()
        paper.abstract = "Abstract text here"
        paper.pdf_url = None
        unified_doc = MagicMock()
        unified_doc.document_type = PAPER
        unified_doc.paper = paper
        text, content_type = get_document_content(unified_doc, "abstract")
        self.assertEqual(text, "Abstract text here")
        self.assertEqual(content_type, "abstract")

    def test_paper_no_abstract_no_pdf_raises(self):
        from researchhub_document.related_models.constants.document_type import PAPER

        paper = MagicMock()
        paper.abstract = None
        paper.pdf_url = None
        unified_doc = MagicMock()
        unified_doc.document_type = PAPER
        unified_doc.paper = paper
        with self.assertRaises(ValueError) as ctx:
            get_document_content(unified_doc, "abstract")
        self.assertIn("Abstract is not available", str(ctx.exception))

    def test_post_with_renderable_text_returns_full_content(self):
        from researchhub_document.related_models.constants.document_type import (
            DISCUSSION,
        )

        post = MagicMock()
        post.renderable_text = "Post content"
        unified_doc = MagicMock()
        unified_doc.document_type = DISCUSSION
        unified_doc.posts.first.return_value = post
        text, content_type = get_document_content(unified_doc, "abstract")
        self.assertEqual(text, "Post content")
        self.assertEqual(content_type, "full_content")

    def test_post_no_content_raises(self):
        from researchhub_document.related_models.constants.document_type import (
            DISCUSSION,
        )

        post = MagicMock()
        post.renderable_text = None
        post.get_full_markdown.side_effect = Exception("nope")
        unified_doc = MagicMock()
        unified_doc.document_type = DISCUSSION
        unified_doc.posts.first.return_value = post
        with self.assertRaises(ValueError) as ctx:
            get_document_content(unified_doc, "abstract")
        self.assertIn("no content", str(ctx.exception))

    def test_document_no_post_raises(self):
        from researchhub_document.related_models.constants.document_type import (
            DISCUSSION,
        )

        unified_doc = MagicMock()
        unified_doc.document_type = DISCUSSION
        unified_doc.posts.first.return_value = None
        with self.assertRaises(ValueError) as ctx:
            get_document_content(unified_doc, "full_content")
        self.assertIn("no post content", str(ctx.exception))

    def test_post_get_full_markdown_returns_full_content(self):
        from researchhub_document.related_models.constants.document_type import (
            DISCUSSION,
        )

        post = MagicMock()
        post.renderable_text = None
        post.get_full_markdown.return_value = "# Full markdown content"
        unified_doc = MagicMock()
        unified_doc.document_type = DISCUSSION
        unified_doc.posts.first.return_value = post
        text, content_type = get_document_content(unified_doc, "full_content")
        self.assertEqual(text, "# Full markdown content")
        self.assertEqual(content_type, "full_content")

    def test_paper_invalid_input_type_raises(self):
        from researchhub_document.related_models.constants.document_type import PAPER

        paper = MagicMock()
        unified_doc = MagicMock()
        unified_doc.document_type = PAPER
        unified_doc.paper = paper
        with self.assertRaises(ValueError) as ctx:
            get_document_content(unified_doc, "invalid_type")
        self.assertIn("Invalid input_type for paper", str(ctx.exception))

    @patch("research_ai.services.expert_finder_service._extract_text_from_pdf_bytes")
    @patch("research_ai.services.expert_finder_service._get_paper_pdf_bytes")
    def test_paper_pdf_returns_extracted_text(self, mock_get_pdf, mock_extract):
        from researchhub_document.related_models.constants.document_type import PAPER

        mock_get_pdf.return_value = b"pdf bytes"
        mock_extract.return_value = "Extracted PDF text"
        paper = MagicMock()
        unified_doc = MagicMock()
        unified_doc.document_type = PAPER
        unified_doc.paper = paper
        text, content_type = get_document_content(unified_doc, "pdf")
        self.assertEqual(text, "Extracted PDF text")
        self.assertEqual(content_type, "pdf")
        mock_get_pdf.assert_called_once_with(paper)
        mock_extract.assert_called_once_with(b"pdf bytes")

    @patch("research_ai.services.expert_finder_service._get_paper_pdf_bytes")
    def test_paper_pdf_not_available_raises(self, mock_get_pdf):
        from researchhub_document.related_models.constants.document_type import PAPER

        mock_get_pdf.return_value = None
        paper = MagicMock()
        unified_doc = MagicMock()
        unified_doc.document_type = PAPER
        unified_doc.paper = paper
        with self.assertRaises(ValueError) as ctx:
            get_document_content(unified_doc, "pdf")
        self.assertIn("PDF is not available", str(ctx.exception))

    @patch("research_ai.services.expert_finder_service._get_paper_pdf_bytes")
    def test_paper_pdf_too_large_raises(self, mock_get_pdf):
        from research_ai.constants import MAX_PDF_SIZE_BYTES
        from researchhub_document.related_models.constants.document_type import PAPER

        mock_get_pdf.return_value = b"x" * (MAX_PDF_SIZE_BYTES + 1)
        paper = MagicMock()
        unified_doc = MagicMock()
        unified_doc.document_type = PAPER
        unified_doc.paper = paper
        with self.assertRaises(ValueError) as ctx:
            get_document_content(unified_doc, "pdf")
        self.assertEqual(str(ctx.exception), PDF_TOO_LARGE_MESSAGE)


class ExtractTextFromPdfBytesTests(TestCase):
    @patch("research_ai.services.expert_finder_service.fitz")
    def test_extract_text_returns_text(self, mock_fitz):
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Page 1 text"
        mock_doc.__iter__ = lambda self: iter([mock_page])
        mock_fitz.open.return_value = mock_doc
        text = _extract_text_from_pdf_bytes(b"pdf bytes")
        self.assertEqual(text, "Page 1 text")
        mock_doc.close.assert_called_once()

    @patch("research_ai.services.expert_finder_service.fitz")
    def test_extract_text_truncates_at_200000(self, mock_fitz):
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = "a" * 250000
        mock_doc.__iter__ = lambda self: iter([mock_page])
        mock_fitz.open.return_value = mock_doc
        text = _extract_text_from_pdf_bytes(b"pdf bytes")
        self.assertEqual(len(text), 200000)
        self.assertEqual(text, "a" * 200000)
        mock_doc.close.assert_called_once()

    @patch("research_ai.services.expert_finder_service.fitz")
    def test_extract_text_failure_raises_value_error(self, mock_fitz):
        mock_fitz.open.side_effect = Exception("corrupt pdf")
        with self.assertRaises(ValueError) as ctx:
            _extract_text_from_pdf_bytes(b"pdf bytes")
        self.assertIn("PDF text extraction failed", str(ctx.exception))
        self.assertIn("corrupt pdf", str(ctx.exception))


class GetPaperPdfBytesTests(TestCase):
    @patch("research_ai.services.expert_finder_service.download_pdf_from_url")
    @patch("research_ai.services.expert_finder_service.create_download_url")
    def test_returns_pdf_from_pdf_url(self, mock_create_url, mock_download):
        paper = MagicMock()
        paper.file = None
        paper.pdf_url = "https://example.com/paper.pdf"
        paper.external_source = "doi"
        paper.id = 1
        mock_file = MagicMock()
        mock_file.read.return_value = b"pdf content"
        mock_download.return_value = mock_file
        mock_create_url.return_value = "https://proxy/paper.pdf"
        result = _get_paper_pdf_bytes(paper)
        self.assertEqual(result, b"pdf content")
        mock_create_url.assert_called_once_with("https://example.com/paper.pdf", "doi")
        mock_download.assert_called_once_with("https://proxy/paper.pdf")

    @patch("research_ai.services.expert_finder_service.download_pdf_from_url")
    def test_returns_pdf_from_paper_file(self, mock_download):
        paper = MagicMock()
        paper.file = MagicMock()
        paper.file.url = "https://s3.example.com/file.pdf"
        paper.id = 1
        mock_file = MagicMock()
        mock_file.read.return_value = b"s3 pdf content"
        mock_download.return_value = mock_file
        result = _get_paper_pdf_bytes(paper)
        self.assertEqual(result, b"s3 pdf content")
        mock_download.assert_called_once_with("https://s3.example.com/file.pdf")

    @patch("research_ai.services.expert_finder_service.download_pdf_from_url")
    def test_falls_back_to_pdf_url_when_file_fails(self, mock_download):
        paper = MagicMock()
        paper.file = MagicMock()
        paper.file.url = "https://s3.example.com/file.pdf"
        paper.pdf_url = "https://example.com/paper.pdf"
        paper.external_source = ""
        paper.id = 1
        mock_file = MagicMock()
        mock_file.read.return_value = b"url pdf content"
        mock_download.side_effect = [Exception("s3 down"), mock_file]
        with patch(
            "research_ai.services.expert_finder_service.create_download_url",
            return_value="https://proxy/paper.pdf",
        ):
            result = _get_paper_pdf_bytes(paper)
        self.assertEqual(result, b"url pdf content")

    def test_returns_none_when_no_url(self):
        paper = MagicMock()
        paper.file = None
        paper.pdf_url = None
        paper.url = None
        result = _get_paper_pdf_bytes(paper)
        self.assertIsNone(result)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ExpertFinderRunSearchIntegrationTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("expert_user")
        self.search = ExpertSearch.objects.create(
            created_by=self.user,
            query="Q",
            status=ExpertSearch.Status.PENDING,
        )

    @override_settings(PRODUCTION=False, TESTING=False)
    @patch(
        "research_ai.services.expert_finder_service.upload_report_to_storage",
        return_value="https://x/r",
    )
    @patch(
        "research_ai.services.expert_finder_service.generate_csv_file",
        return_value=b"c",
    )
    @patch(
        "research_ai.services.expert_finder_service.generate_pdf_report",
        return_value=b"p",
    )
    @patch("research_ai.services.expert_finder_service.OpenAIExpertFinderService")
    def test_run_success_persists_and_returns_completed(
        self, mock_openai_class, _pdf, _csv, _up
    ):
        expert_json = (
            '{"experts": ['
            '{"email": "u@mit.edu", "first_name": "U", "last_name": "V", '
            '"academic_title": "Prof", "affiliation": "MIT", "expertise": "X", "notes": "N", "sources": []}'  # noqa: E501
            "]}"
        )
        mock_oa = MagicMock()
        mock_oa.model_id = "m1"
        mock_oa.invoke.return_value = expert_json
        mock_openai_class.return_value = mock_oa
        r = run_expert_finder_search(
            str(self.search.id),
            "query",
            {
                "expert_count": 1,
                "expertise_level": [ExpertiseLevel.ALL_LEVELS],
                "region": Region.ALL_REGIONS,
            },
        )
        self.assertEqual(r["status"], ExpertSearch.Status.COMPLETED)
        self.assertEqual(r["expert_count"], 1)
        se = SearchExpert.objects.filter(expert_search_id=self.search.id)
        self.assertEqual(se.count(), 1)
        self.assertTrue(Expert.objects.filter(email="u_test@mit.edu").exists())
        self.assertFalse(Expert.objects.filter(email="u@mit.edu").exists())
