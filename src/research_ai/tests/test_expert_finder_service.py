from unittest.mock import MagicMock, patch

from django.test import TestCase

from research_ai.models import ExpertSearch
from research_ai.services.expert_finder_service import (
    ExpertFinderService,
    PDF_TOO_LARGE_MESSAGE,
    get_document_content,
    _extract_text_from_pdf_bytes,
    _get_paper_pdf_bytes,
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
    def test_paper_pdf_returns_extracted_text(
        self, mock_get_pdf, mock_extract
    ):
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

    def test_clean_url_no_query_returns_unchanged(self):
        service = ExpertFinderService()
        url = "https://example.com/page"
        self.assertEqual(service._clean_url(url), url)

    def test_extract_citations_skips_empty_url(self):
        service = ExpertFinderService()
        text = "See [empty]() and [real](https://x.com) here."
        cleaned, citations = service._extract_citations(text)
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0]["url"], "https://x.com")

    def test_parse_markdown_table_no_valid_table_returns_empty(self):
        service = ExpertFinderService()
        experts = service._parse_markdown_table("No table here.\nJust text.")
        self.assertEqual(experts, [])

    def test_parse_markdown_table_separator_line_skipped(self):
        service = ExpertFinderService()
        markdown = """
        | Name | Title | Affiliation | Expertise | Email |
        |------|-------|-------------|-----------|-------|
        | Jane | Prof | MIT | ML | jane@mit.edu |
        """
        experts = service._parse_markdown_table(markdown)
        self.assertEqual(len(experts), 1)
        self.assertEqual(experts[0]["name"], "Jane")

    def test_parse_markdown_table_institution_and_notes_columns(self):
        service = ExpertFinderService()
        markdown = """
        | Name | Title | Institution | Expertise | Email | Note |
        |------|-------|-------------|-----------|-------|------|
        | Bob | Dr | Stanford | NLP | bob@stanford.edu | See [link](https://example.com) |
        """
        experts = service._parse_markdown_table(markdown)
        self.assertEqual(len(experts), 1)
        self.assertEqual(experts[0]["affiliation"], "Stanford")
        self.assertEqual(experts[0]["notes"], "See")
        self.assertEqual(len(experts[0]["sources"]), 1)
        self.assertEqual(experts[0]["sources"][0]["url"], "https://example.com")

    def test_parse_markdown_table_skips_row_with_fewer_than_five_cells(self):
        service = ExpertFinderService()
        markdown = """
        | Name | Title | Affiliation | Expertise | Email |
        |------|-------|-------------|-----------|-------|
        | Jane | Prof | MIT | jane@mit.edu |
        | John | Dr | Stanford | AI | john@stanford.edu |
        """
        experts = service._parse_markdown_table(markdown)
        self.assertEqual(len(experts), 1)
        self.assertEqual(experts[0]["name"], "John")

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
    def test_process_expert_search_calls_progress_callback(
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
        callback = MagicMock()

        service = ExpertFinderService()
        result = service.process_expert_search(
            search_id="2",
            query="AI",
            config={},
            progress_callback=callback,
        )
        self.assertEqual(result["status"], ExpertSearch.Status.COMPLETED)
        self.assertGreater(callback.call_count, 1)
        final_call = callback.call_args_list[-1]
        self.assertEqual(final_call[0][0], "2")
        self.assertEqual(final_call[0][1], 100)
        self.assertIn("complete", final_call[0][2].lower())

    @patch("research_ai.services.expert_finder_service.BedrockLLMService")
    @patch("research_ai.services.expert_finder_service.ProgressService")
    def test_process_expert_search_returns_failed_when_no_table_parsed(
        self, mock_progress, mock_bedrock
    ):
        """When LLM returns prose instead of a table, result is FAILED with error_message."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = (
            "I cannot proceed. The input contains only placeholder text. "
            "Please provide the actual research description."
        )
        mock_llm.model_id = "test-model"
        mock_bedrock.return_value = mock_llm
        publish = MagicMock()
        mock_progress.return_value.publish_progress_sync = publish

        service = ExpertFinderService()
        result = service.process_expert_search(
            search_id="3",
            query="Placeholder RFP text",
            config={"expert_count": 5},
        )
        self.assertEqual(result["status"], ExpertSearch.Status.FAILED)
        self.assertEqual(result["expert_count"], 0)
        self.assertEqual(result["experts"], [])
        self.assertEqual(result["report_urls"], {})
        self.assertIn("placeholder text", result["error_message"])
        self.assertEqual(result["error_message"], mock_llm.invoke.return_value)
        failed_call = next(
            c for c in publish.call_args_list
            if c[0][2].get("status") == ExpertSearch.Status.FAILED
        )
        self.assertIsNotNone(failed_call)

    @patch("research_ai.services.expert_finder_service.BedrockLLMService")
    @patch("research_ai.services.expert_finder_service.ProgressService")
    def test_process_expert_search_error_message_truncated_when_llm_response_long(
        self, mock_progress, mock_bedrock
    ):
        """When LLM returns non-table response, error_message is truncated to MAX_ERROR_MESSAGE_LENGTH."""
        from research_ai.services.expert_finder_service import MAX_ERROR_MESSAGE_LENGTH

        long_response = "No table here. " + "x" * (MAX_ERROR_MESSAGE_LENGTH + 1000)
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = long_response
        mock_llm.model_id = "test-model"
        mock_bedrock.return_value = mock_llm
        mock_progress.return_value.publish_progress_sync = MagicMock()

        service = ExpertFinderService()
        result = service.process_expert_search(
            search_id="3b",
            query="Q",
            config={},
        )
        self.assertEqual(result["status"], ExpertSearch.Status.FAILED)
        self.assertEqual(len(result["error_message"]), MAX_ERROR_MESSAGE_LENGTH)

    @patch("research_ai.services.expert_finder_service.BedrockLLMService")
    @patch("research_ai.services.expert_finder_service.ProgressService")
    def test_process_expert_search_on_exception_publishes_failed_and_reraises(
        self, mock_progress, mock_bedrock
    ):
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("LLM down")
        mock_bedrock.return_value = mock_llm
        publish = MagicMock()
        mock_progress.return_value.publish_progress_sync = publish

        service = ExpertFinderService()
        with self.assertRaises(RuntimeError):
            service.process_expert_search(
                search_id="3",
                query="AI",
                config={},
            )
        failed_call = next(
            c for c in publish.call_args_list
            if c[0][2].get("status") == ExpertSearch.Status.FAILED
        )
        self.assertIsNotNone(failed_call)

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
    def test_process_expert_search_config_expert_count_alternate_keys(
        self, mock_upload, mock_csv, mock_pdf, mock_progress, mock_bedrock
    ):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = """
        | Name | Title | Affiliation | Expertise | Email |
        |------|-------|-------------|-----------|-------|
        | Alice | Prof | MIT | AI | alice@mit.edu |
        """
        mock_llm.model_id = "model"
        mock_bedrock.return_value = mock_llm
        mock_progress.return_value.publish_progress_sync = MagicMock()

        service = ExpertFinderService()
        result = service.process_expert_search(
            search_id="4",
            query="Q",
            config={"expert_count": 5},
        )
        self.assertEqual(result["status"], ExpertSearch.Status.COMPLETED)

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
    def test_process_expert_search_expertise_level_string_and_list(
        self, mock_upload, mock_csv, mock_pdf, mock_progress, mock_bedrock
    ):
        from research_ai.constants import ExpertiseLevel

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = """
        | Name | Title | Affiliation | Expertise | Email |
        |------|-------|-------------|-----------|-------|
        | Alice | Prof | MIT | AI | alice@mit.edu |
        """
        mock_llm.model_id = "model"
        mock_bedrock.return_value = mock_llm
        mock_progress.return_value.publish_progress_sync = MagicMock()

        service = ExpertFinderService()
        result = service.process_expert_search(
            search_id="5",
            query="Q",
            config={"expertise_level": ExpertiseLevel.EARLY_CAREER},
        )
        self.assertEqual(result["status"], ExpertSearch.Status.COMPLETED)

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
    def test_process_expert_search_exception_calls_progress_callback(
        self, mock_upload, mock_csv, mock_pdf, mock_progress, mock_bedrock
    ):
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = ValueError("fail")
        mock_bedrock.return_value = mock_llm
        mock_progress.return_value.publish_progress_sync = MagicMock()
        callback = MagicMock()

        service = ExpertFinderService()
        with self.assertRaises(ValueError):
            service.process_expert_search(
                search_id="6",
                query="Q",
                config={},
                progress_callback=callback,
            )
        error_call = next(
            (c for c in callback.call_args_list if c[0][1] == 0),
            None,
        )
        self.assertIsNotNone(error_call)
        self.assertIn("fail", error_call[0][2])
