from unittest.mock import MagicMock, patch

from django.test import TestCase

from research_ai.models import ExpertSearch
from research_ai.services.expert_finder_service import (
    ExpertFinderService,
    get_document_content,
    _extract_text_from_pdf_url,
)


class GetDocumentContentTests(TestCase):
    def test_paper_abstract_returns_abstract(self):
        from researchhub_document.related_models.constants.document_type import (
            PAPER,
        )

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
        from researchhub_document.related_models.constants.document_type import (
            PAPER,
        )

        paper = MagicMock()
        paper.abstract = None
        paper.pdf_url = None
        unified_doc = MagicMock()
        unified_doc.document_type = PAPER
        unified_doc.paper = paper
        with self.assertRaises(ValueError) as ctx:
            get_document_content(unified_doc, "abstract")
        self.assertIn("no abstract or PDF", str(ctx.exception))

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


class ExtractTextFromPdfUrlTests(TestCase):
    @patch("research_ai.services.expert_finder_service.urllib.request.urlopen")
    @patch("research_ai.services.expert_finder_service.fitz")
    def test_extract_text_returns_text(self, mock_fitz, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"pdf bytes"
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Page 1 text"
        mock_doc.__iter__ = lambda self: iter([mock_page])
        mock_fitz.open.return_value = mock_doc
        text = _extract_text_from_pdf_url("http://example.com/file.pdf")
        self.assertEqual(text, "Page 1 text")
        mock_doc.close.assert_called_once()


class ExpertFinderServiceParseTests(TestCase):
    def test_parse_markdown_table_returns_experts(self):
        service = ExpertFinderService()
        markdown = """
        | Name | Title | Affiliation | Expertise | Email |
        |------|-------|-------------|-----------|-------|
        | Jane Doe | Prof | MIT | ML | jane@mit.edu |
        | John Smith | Dr | Stanford | NLP | john@stanford.edu |
        """
        experts = service._parse_markdown_table(markdown)
        self.assertEqual(len(experts), 2)
        self.assertEqual(experts[0]["name"], "Jane Doe")
        self.assertEqual(experts[0]["email"], "jane@mit.edu")
        self.assertEqual(experts[1]["name"], "John Smith")

    def test_parse_markdown_table_skips_invalid_email(self):
        service = ExpertFinderService()
        markdown = """
        | Name | Title | Affiliation | Expertise | Email |
        |------|-------|-------------|-----------|-------|
        | No Email | Prof | MIT | ML | not-an-email |
        """
        experts = service._parse_markdown_table(markdown)
        self.assertEqual(len(experts), 0)

    def test_extract_citations(self):
        service = ExpertFinderService()
        text = "See [this paper](https://example.com/doc?utm_x=1) for more."
        cleaned, citations = service._extract_citations(text)
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0]["text"], "this paper")
        self.assertIn("example.com", citations[0]["url"])
        self.assertNotIn("utm_", citations[0]["url"])

    def test_clean_url_removes_utm(self):
        service = ExpertFinderService()
        url = "https://example.com/page?utm_source=foo&bar=baz"
        self.assertEqual(
            service._clean_url(url),
            "https://example.com/page?bar=baz",
        )

    @patch("research_ai.services.expert_finder_service.BedrockLLMService")
    @patch("research_ai.services.expert_finder_service.ProgressService")
    @patch(
        "research_ai.services.expert_finder_service.generate_pdf_report",
        return_value=b"pdf",
    )
    @patch(
        "research_ai.services.expert_finder_service.generate_csv_file",
        return_value=b"csv",
    )
    @patch(
        "research_ai.services.expert_finder_service.upload_report_to_storage",
        side_effect=lambda sid, content, ext, ct: f"https://storage/{sid}.{ext}",
    )
    def test_process_expert_search_success(
        self,
        mock_upload,
        mock_csv,
        mock_pdf,
        mock_progress,
        mock_bedrock,
    ):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = """
        | Name | Title | Affiliation | Expertise | Email |
        |------|-------|-------------|-----------|-------|
        | Alice | Prof | MIT | AI | alice@mit.edu |
        """
        mock_llm.model_id = "test-model"
        mock_bedrock.return_value = mock_llm
        mock_progress.return_value.publish_progress_sync = MagicMock()

        service = ExpertFinderService()
        result = service.process_expert_search(
            search_id="1",
            query="AI research",
            config={"expert_count": 10},
        )
        self.assertEqual(result["status"], ExpertSearch.Status.COMPLETED)
        self.assertEqual(result["expert_count"], 1)
        self.assertEqual(result["experts"][0]["name"], "Alice")
        self.assertIn("pdf", result["report_urls"])
        self.assertIn("csv", result["report_urls"])
