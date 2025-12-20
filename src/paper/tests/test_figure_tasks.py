from io import BytesIO
from unittest.mock import MagicMock, patch

from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.test import TestCase
from PIL import Image

from paper.models import Figure
from paper.services.bedrock_primary_image_service import MIN_PRIMARY_SCORE_THRESHOLD
from paper.tasks import create_pdf_screenshot, extract_pdf_figures, select_primary_image
from paper.tests import helpers

test_storage = FileSystemStorage()


@patch.object(Figure._meta.get_field("file"), "storage", test_storage)
@patch.object(Figure._meta.get_field("thumbnail"), "storage", test_storage)
class ExtractPdfFiguresTaskTests(TestCase):
    """Test suite for extract_pdf_figures Celery task."""

    def setUp(self):
        """Set up test environment."""
        self.paper = helpers.create_paper(title="Test Paper")

    def test_extract_pdf_figures_no_paper(self):
        """Test that task handles nonexistent paper gracefully."""
        result = extract_pdf_figures(99999)
        self.assertFalse(result)

    def test_extract_pdf_figures_no_file(self):
        """Test that task retries when paper has no PDF file."""
        paper = helpers.create_paper(title="No PDF Paper")
        paper.file = None
        paper.save()

        with patch(
            "paper.tasks.figure_tasks.extract_pdf_figures.apply_async"
        ) as mock_retry:
            result = extract_pdf_figures(paper.id)
            self.assertFalse(result)
            mock_retry.assert_called_once()

    @patch("paper.tasks.figure_tasks.requests.get")
    @patch("paper.tasks.figure_tasks.FigureExtractionService")
    @patch("paper.tasks.figure_tasks.select_primary_image.apply_async")
    def test_extract_pdf_figures_success(
        self, mock_select_task, mock_service_class, mock_get
    ):
        """Test successful figure extraction."""
        # Create a paper with a file
        paper = helpers.create_paper(title="Test Paper")
        paper.file.name = "test.pdf"
        paper.save()

        # Mock PDF content
        mock_response = MagicMock()
        mock_response.content = b"fake pdf content"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        # Mock extraction service
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        # Create mock extracted figures
        img = Image.new("RGB", (500, 500), color="blue")
        buffer = BytesIO()
        img.save(buffer, format="JPEG")
        content_file = ContentFile(buffer.getvalue(), name="test-figure.jpg")
        mock_service.extract_figures_from_pdf.return_value = [content_file]

        result = extract_pdf_figures(paper.id)

        self.assertTrue(result)
        mock_service.extract_figures_from_pdf.assert_called_once()
        mock_select_task.assert_called_once_with(
            (paper.id,),
            {"skip_feed_refresh_extraction_check": False},
            priority=5,
        )

    @patch("paper.tasks.figure_tasks.requests.get")
    @patch("paper.tasks.figure_tasks.FigureExtractionService")
    def test_extract_pdf_figures_handles_duplicates(self, mock_service_class, mock_get):
        """Test that task avoids creating duplicate figures."""
        paper = helpers.create_paper(title="Test Paper")
        paper.file.name = "test.pdf"
        paper.save()

        # Create existing figure with filename matching extraction service format
        img = Image.new("RGB", (500, 500), color="blue")
        buffer = BytesIO()
        img.save(buffer, format="JPEG")
        filename = f"{paper.id}-page0-img0.jpg"
        existing_figure = Figure.objects.create(
            paper=paper,
            figure_type=Figure.FIGURE,
            file=ContentFile(buffer.getvalue(), name=filename),
        )
        # Refresh to get the actual stored file path
        existing_figure.refresh_from_db()
        # Extract just the filename part (what the task does)
        stored_filename = existing_figure.file.name.split("/")[-1]

        # Mock PDF content
        mock_response = MagicMock()
        mock_response.content = b"fake pdf content"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        # Mock extraction service
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        # Return figure with same filename (as extraction service would generate)
        # Use the stored filename to ensure exact match
        mock_service.extract_figures_from_pdf.return_value = [
            ContentFile(buffer.getvalue(), name=stored_filename)
        ]

        initial_count = Figure.objects.filter(
            paper=paper, figure_type=Figure.FIGURE
        ).count()
        self.assertEqual(initial_count, 1)

        with patch("paper.tasks.figure_tasks.select_primary_image.apply_async"):
            result = extract_pdf_figures(paper.id)

        self.assertTrue(result)
        # Should not create duplicate
        final_count = Figure.objects.filter(
            paper=paper, figure_type=Figure.FIGURE
        ).count()
        self.assertEqual(final_count, initial_count, "Duplicate figure was created")

    @patch("paper.tasks.figure_tasks.requests.get")
    @patch("paper.tasks.figure_tasks.extract_pdf_figures.apply_async")
    def test_extract_pdf_figures_retries_on_error(self, mock_retry, mock_get):
        """Test that task retries on failure."""
        paper = helpers.create_paper(title="Test Paper")
        paper.file.name = "test.pdf"
        paper.save()

        # Mock request failure
        mock_get.side_effect = Exception("Network error")

        result = extract_pdf_figures(paper.id, retry=0)

        self.assertFalse(result)
        mock_retry.assert_called_once()

    @patch("paper.tasks.figure_tasks.download_pdf_from_url")
    @patch("paper.tasks.figure_tasks.create_download_url")
    @patch("paper.tasks.figure_tasks.FigureExtractionService")
    @patch("paper.tasks.figure_tasks.select_primary_image.apply_async")
    def test_extract_pdf_figures_uses_pdf_url_when_file_empty(
        self,
        mock_select_task,
        mock_service_class,
        mock_create_url,
        mock_download_pdf,
    ):
        """Test that task uses pdf_url when paper.file is empty."""
        paper = helpers.create_paper(title="Test Paper")
        paper.file = None
        paper.pdf_url = "https://arxiv.org/pdf/1234.56789.pdf"
        paper.external_source = "arxiv"
        paper.save()

        # Mock PDF download
        pdf_content = b"fake pdf content"
        pdf_file = ContentFile(pdf_content, name="paper.pdf")
        mock_download_pdf.return_value = pdf_file
        mock_create_url.return_value = "https://scraper/?url=test"

        # Mock extraction service
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        # Create mock extracted figures
        img = Image.new("RGB", (500, 500), color="blue")
        buffer = BytesIO()
        img.save(buffer, format="JPEG")
        content_file = ContentFile(buffer.getvalue(), name="test-figure.jpg")
        mock_service.extract_figures_from_pdf.return_value = [content_file]

        result = extract_pdf_figures(paper.id)

        self.assertTrue(result)
        mock_create_url.assert_called_once_with(paper.pdf_url, paper.external_source)
        mock_download_pdf.assert_called_once()
        mock_service.extract_figures_from_pdf.assert_called_once_with(
            pdf_content, paper.id
        )
        mock_select_task.assert_called_once_with(
            (paper.id,),
            {"skip_feed_refresh_extraction_check": False},
            priority=5,
        )

    @patch("paper.tasks.figure_tasks.download_pdf_from_url")
    @patch("paper.tasks.figure_tasks.create_download_url")
    @patch("paper.tasks.figure_tasks.FigureExtractionService")
    @patch("paper.tasks.figure_tasks.select_primary_image.apply_async")
    def test_extract_pdf_figures_saves_pdf_to_file_when_downloaded(
        self,
        mock_select_task,
        mock_service_class,
        mock_create_url,
        mock_download_pdf,
    ):
        """Test that task saves downloaded PDF to paper.file for future use."""
        paper = helpers.create_paper(title="Test Paper")
        paper.file = None
        paper.pdf_url = "https://arxiv.org/pdf/1234.56789.pdf"
        paper.external_source = "arxiv"
        paper.save()

        # Mock PDF download
        pdf_content = b"fake pdf content"
        pdf_file = ContentFile(pdf_content, name="paper.pdf")
        mock_download_pdf.return_value = pdf_file
        mock_create_url.return_value = "https://scraper/?url=test"

        # Mock extraction service
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        # Create mock extracted figures
        img = Image.new("RGB", (500, 500), color="blue")
        buffer = BytesIO()
        img.save(buffer, format="JPEG")
        content_file = ContentFile(buffer.getvalue(), name="test-figure.jpg")
        mock_service.extract_figures_from_pdf.return_value = [content_file]

        result = extract_pdf_figures(paper.id)

        self.assertTrue(result)

    @patch("paper.tasks.figure_tasks.requests.get")
    @patch("paper.tasks.figure_tasks.download_pdf_from_url")
    @patch("paper.tasks.figure_tasks.create_download_url")
    @patch("paper.tasks.figure_tasks.FigureExtractionService")
    @patch("paper.tasks.figure_tasks.select_primary_image.apply_async")
    def test_extract_pdf_figures_falls_back_to_pdf_url_when_file_fails(
        self,
        mock_select_task,
        mock_service_class,
        mock_create_url,
        mock_download_pdf,
        mock_get,
    ):
        """Test that task falls back to pdf_url when file download fails."""
        paper = helpers.create_paper(title="Test Paper")
        paper.file.name = "test.pdf"
        paper.pdf_url = "https://arxiv.org/pdf/1234.56789.pdf"
        paper.external_source = "arxiv"
        paper.save()

        # Mock file download failure
        mock_get.side_effect = Exception("File download failed")

        # Mock PDF download from pdf_url
        pdf_content = b"fake pdf content from url"
        pdf_file = ContentFile(pdf_content, name="paper.pdf")
        mock_download_pdf.return_value = pdf_file
        mock_create_url.return_value = "https://scraper/?url=test"

        # Mock extraction service
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        # Create mock extracted figures
        img = Image.new("RGB", (500, 500), color="blue")
        buffer = BytesIO()
        img.save(buffer, format="JPEG")
        content_file = ContentFile(buffer.getvalue(), name="test-figure.jpg")
        mock_service.extract_figures_from_pdf.return_value = [content_file]

        result = extract_pdf_figures(paper.id)

        self.assertTrue(result)
        # Should have tried file first, then pdf_url
        mock_get.assert_called_once()
        mock_create_url.assert_called_once_with(paper.pdf_url, paper.external_source)
        mock_download_pdf.assert_called_once()
        mock_service.extract_figures_from_pdf.assert_called_once_with(
            pdf_content, paper.id
        )

    @patch("paper.tasks.figure_tasks.download_pdf_from_url")
    @patch("paper.tasks.figure_tasks.create_download_url")
    @patch("paper.tasks.figure_tasks.extract_pdf_figures.apply_async")
    def test_extract_pdf_figures_retries_when_pdf_url_download_fails(
        self, mock_retry, mock_create_url, mock_download_pdf
    ):
        """Test that task retries when pdf_url download fails."""
        paper = helpers.create_paper(title="Test Paper")
        paper.file = None
        paper.pdf_url = "https://arxiv.org/pdf/1234.56789.pdf"
        paper.external_source = "arxiv"
        paper.save()

        # Mock download failure
        mock_download_pdf.side_effect = Exception("Download failed")
        mock_create_url.return_value = "https://scraper/?url=test"

        result = extract_pdf_figures(paper.id)

        self.assertFalse(result)
        mock_retry.assert_called_once()

    @patch("paper.tasks.figure_tasks.extract_pdf_figures.apply_async")
    def test_extract_pdf_figures_retries_when_no_file_and_no_pdf_url(self, mock_retry):
        """Test that task retries when both file and pdf_url are empty."""
        paper = helpers.create_paper(title="Test Paper")
        paper.file = None
        paper.pdf_url = None
        paper.save()

        result = extract_pdf_figures(paper.id)

        self.assertFalse(result)
        mock_retry.assert_called_once()


@patch.object(Figure._meta.get_field("file"), "storage", test_storage)
@patch.object(Figure._meta.get_field("thumbnail"), "storage", test_storage)
class SelectPrimaryImageTaskTests(TestCase):
    """Test suite for select_primary_image Celery task."""

    def setUp(self):
        """Set up test environment."""
        self.paper = helpers.create_paper(
            title="Test Paper", raw_authors=["Test Author"]
        )

    def _create_test_figure(
        self, paper=None, is_primary=False, figure_type=Figure.FIGURE
    ):
        """Create a test figure."""
        if paper is None:
            paper = self.paper

        img = Image.new("RGB", (500, 500), color="blue")
        buffer = BytesIO()
        img.save(buffer, format="JPEG")
        return Figure.objects.create(
            paper=paper,
            figure_type=figure_type,
            is_primary=is_primary,
            file=ContentFile(buffer.getvalue(), name="test-figure.jpg"),
        )

    def test_select_primary_image_no_paper(self):
        """Test that task handles nonexistent paper gracefully."""
        result = select_primary_image(99999)
        self.assertFalse(result)

    def test_select_primary_image_no_figures_creates_preview(self):
        """Test that task creates preview when no figures exist."""
        paper = helpers.create_paper(title="No Figures Paper")
        paper.file.name = "test.pdf"
        paper.save()

        with patch(
            "paper.tasks.figure_tasks.create_pdf_screenshot"
        ) as mock_create_preview:
            mock_create_preview.return_value = True
            result = select_primary_image(paper.id)

            self.assertTrue(result)
            mock_create_preview.assert_called_once_with(
                paper, skip_feed_refresh_extraction_check=False
            )

    def test_select_primary_image_keeps_existing_primary(self):
        """Test that task keeps existing primary if no figures."""
        paper = helpers.create_paper(title="No Figures Paper")
        paper.file.name = "test.pdf"
        paper.save()

        # Create existing primary preview
        preview = self._create_test_figure(
            paper=paper, figure_type=Figure.PREVIEW, is_primary=True
        )

        result = select_primary_image(paper.id)

        self.assertTrue(result)
        # Should still be primary
        preview.refresh_from_db()
        self.assertTrue(preview.is_primary)

    @patch("paper.tasks.figure_tasks.BedrockPrimaryImageService")
    def test_select_primary_image_success(self, mock_service_class):
        """Test successful primary image selection."""
        figure1 = self._create_test_figure()
        figure2 = self._create_test_figure()

        # Mock Bedrock service
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        mock_service.select_primary_image.return_value = (figure1.id, 75.5)

        result = select_primary_image(self.paper.id)

        self.assertTrue(result)
        mock_service.select_primary_image.assert_called_once()
        figure1.refresh_from_db()
        self.assertTrue(figure1.is_primary)
        figure2.refresh_from_db()
        self.assertFalse(figure2.is_primary)

    @patch("paper.tasks.figure_tasks.BedrockPrimaryImageService")
    @patch("paper.tasks.figure_tasks.create_pdf_screenshot")
    def test_select_primary_image_low_score_uses_preview(
        self, mock_create_preview, mock_service_class
    ):
        """Test that task uses preview when score is below threshold."""
        figure1 = self._create_test_figure()

        # Mock Bedrock service returning low score
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        mock_service.select_primary_image.return_value = (
            figure1.id,
            MIN_PRIMARY_SCORE_THRESHOLD - 10,
        )

        mock_create_preview.return_value = True

        result = select_primary_image(self.paper.id)

        self.assertTrue(result)
        mock_create_preview.assert_called_once_with(
            self.paper, skip_feed_refresh_extraction_check=False
        )

    @patch("paper.tasks.figure_tasks.BedrockPrimaryImageService")
    @patch("paper.tasks.figure_tasks.create_pdf_screenshot")
    def test_select_primary_image_no_selection_uses_preview(
        self, mock_create_preview, mock_service_class
    ):
        """Test that task uses preview when no figure is selected."""
        self._create_test_figure()

        # Mock Bedrock service returning no selection
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        mock_service.select_primary_image.return_value = (None, None)

        mock_create_preview.return_value = True

        result = select_primary_image(self.paper.id)

        self.assertTrue(result)
        mock_create_preview.assert_called_once_with(
            self.paper, skip_feed_refresh_extraction_check=False
        )

    @patch("paper.tasks.figure_tasks.BedrockPrimaryImageService")
    @patch("paper.tasks.figure_tasks.select_primary_image.apply_async")
    def test_select_primary_image_retries_on_error(
        self, mock_retry, mock_service_class
    ):
        """Test that task retries on failure."""
        self._create_test_figure()

        # Mock Bedrock service failure
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        mock_service.select_primary_image.side_effect = Exception("Bedrock error")

        result = select_primary_image(self.paper.id, retry=0)

        self.assertFalse(result)
        mock_retry.assert_called_once()


@patch.object(Figure._meta.get_field("file"), "storage", test_storage)
@patch.object(Figure._meta.get_field("thumbnail"), "storage", test_storage)
class CreatePdfScreenshotTests(TestCase):
    """Test suite for create_pdf_screenshot helper function."""

    def setUp(self):
        """Set up test environment."""
        self.paper = helpers.create_paper(title="Test Paper")
        self.paper.file.name = "test.pdf"
        self.paper.save()

    @patch("paper.tasks.figure_tasks.requests.get")
    @patch("paper.tasks.figure_tasks.fitz")
    def test_create_pdf_screenshot_success(self, mock_fitz, mock_get):
        """Test successful preview creation."""
        # Mock PDF content
        mock_response = MagicMock()
        mock_response.content = b"fake pdf content"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        # Create valid PNG image bytes for the mock
        img = Image.new("RGB", (500, 500), color="blue")
        png_buffer = BytesIO()
        img.save(png_buffer, format="PNG")
        valid_png_bytes = png_buffer.getvalue()

        # Mock PyMuPDF
        mock_doc = MagicMock()
        mock_fitz.open.return_value = mock_doc
        mock_doc.__len__.return_value = 1

        mock_page = MagicMock()
        mock_doc.__getitem__.return_value = mock_page

        mock_pixmap = MagicMock()
        mock_pixmap.pil_tobytes.return_value = valid_png_bytes
        mock_page.get_pixmap.return_value = mock_pixmap

        result = create_pdf_screenshot(self.paper)

        self.assertTrue(result)
        preview = Figure.objects.filter(
            paper=self.paper, figure_type=Figure.PREVIEW
        ).first()
        self.assertIsNotNone(preview)
        self.assertTrue(preview.is_primary)

    @patch("paper.tasks.figure_tasks.requests.get")
    @patch("paper.tasks.figure_tasks.fitz")
    def test_create_pdf_screenshot_uses_existing_preview(self, mock_fitz, mock_get):
        """Test that function uses existing preview if available."""
        # Create existing preview
        img = Image.new("RGB", (500, 500), color="blue")
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        existing_preview = Figure.objects.create(
            paper=self.paper,
            figure_type=Figure.PREVIEW,
            is_primary=False,
            file=ContentFile(buffer.getvalue(), name="existing-preview.png"),
        )

        result = create_pdf_screenshot(self.paper)

        self.assertTrue(result)
        existing_preview.refresh_from_db()
        self.assertTrue(existing_preview.is_primary)

    def test_create_pdf_screenshot_no_file(self):
        """Test that function handles paper without PDF file."""
        paper = helpers.create_paper(title="No PDF Paper")
        paper.file = None
        paper.save()

        result = create_pdf_screenshot(paper)

        self.assertFalse(result)


class TriggerFigureExtractionTests(TestCase):
    """Test suite for trigger_figure_extraction_for_paper function."""

    def setUp(self):
        """Set up test environment."""
        self.paper = helpers.create_paper(title="Test Paper")

    @patch("paper.tasks.figure_tasks.PRODUCTION", False)
    @patch("paper.tasks.figure_tasks.extract_pdf_figures.apply_async")
    def test_not_in_production_returns_false(self, mock_extract):
        """Test that function returns False when not in PRODUCTION."""
        from paper.tasks.figure_tasks import trigger_figure_extraction_for_paper

        result = trigger_figure_extraction_for_paper(self.paper.id, 100)
        self.assertFalse(result)
        mock_extract.assert_not_called()

    @patch("paper.tasks.figure_tasks.PRODUCTION", True)
    @patch("paper.tasks.figure_tasks.extract_pdf_figures.apply_async")
    def test_below_threshold_returns_false(self, mock_extract):
        """Test that function returns False when hot_score_v2 < 75."""
        from paper.tasks.figure_tasks import trigger_figure_extraction_for_paper

        result = trigger_figure_extraction_for_paper(self.paper.id, 50)
        self.assertFalse(result)
        mock_extract.assert_not_called()

    @patch("paper.tasks.figure_tasks.PRODUCTION", True)
    @patch("paper.tasks.figure_tasks.extract_pdf_figures.apply_async")
    def test_above_threshold_triggers_extraction(self, mock_extract):
        """Test that function triggers extraction when hot_score_v2 >= 75."""
        from paper.tasks.figure_tasks import trigger_figure_extraction_for_paper

        result = trigger_figure_extraction_for_paper(self.paper.id, 100)
        self.assertTrue(result)
        mock_extract.assert_called_once_with(
            (self.paper.id,),
            {"skip_feed_refresh_extraction_check": True},
            priority=6,
        )

    @patch("paper.tasks.figure_tasks.PRODUCTION", True)
    @patch("paper.tasks.figure_tasks.extract_pdf_figures.apply_async")
    def test_exactly_at_threshold_triggers_extraction(self, mock_extract):
        """Test that function triggers extraction when hot_score_v2 == 75."""
        from paper.tasks.figure_tasks import trigger_figure_extraction_for_paper

        result = trigger_figure_extraction_for_paper(self.paper.id, 75)
        self.assertTrue(result)
        mock_extract.assert_called_once()

    @patch("paper.tasks.figure_tasks.PRODUCTION", True)
    @patch("paper.tasks.figure_tasks.extract_pdf_figures.apply_async")
    def test_already_has_figures_returns_false(self, mock_extract):
        """Test that function returns False when paper already has figures."""
        from paper.tasks.figure_tasks import trigger_figure_extraction_for_paper

        with patch.object(Figure._meta.get_field("file"), "storage", test_storage):
            Figure.objects.create(
                paper=self.paper,
                figure_type=Figure.FIGURE,
                file=ContentFile(b"fake", name="test.jpg"),
            )
        result = trigger_figure_extraction_for_paper(self.paper.id, 100)
        self.assertFalse(result)
        mock_extract.assert_not_called()

    @patch("paper.tasks.figure_tasks.PRODUCTION", True)
    def test_paper_not_found_returns_false(self):
        """Test that function handles nonexistent paper gracefully."""
        from paper.tasks.figure_tasks import trigger_figure_extraction_for_paper

        result = trigger_figure_extraction_for_paper(99999, 100)
        self.assertFalse(result)

    @patch("paper.tasks.figure_tasks.PRODUCTION", True)
    @patch("paper.tasks.figure_tasks.extract_pdf_figures.apply_async")
    @patch("paper.tasks.figure_tasks.logger")
    def test_error_handling_returns_false(self, mock_logger, mock_extract):
        """Test that exceptions are caught and logged."""
        from paper.tasks.figure_tasks import trigger_figure_extraction_for_paper

        # Make Paper.objects.get raise an exception
        with patch("paper.tasks.figure_tasks.Paper.objects.get") as mock_get:
            mock_get.side_effect = Exception("Database error")
            result = trigger_figure_extraction_for_paper(self.paper.id, 100)
            self.assertFalse(result)
            mock_extract.assert_not_called()


@patch.object(Figure._meta.get_field("file"), "storage", test_storage)
@patch.object(Figure._meta.get_field("thumbnail"), "storage", test_storage)
class SyncPrimarySelectionTests(TestCase):
    """Test suite for sync_primary_selection parameter in extract_pdf_figures."""

    def setUp(self):
        """Set up test environment."""
        self.paper = helpers.create_paper(title="Test Paper")
        self.paper.file.name = "test.pdf"
        self.paper.save()

    @patch("paper.tasks.figure_tasks.requests.get")
    @patch("paper.tasks.figure_tasks.FigureExtractionService")
    @patch("paper.tasks.figure_tasks.select_primary_image")
    def test_sync_primary_selection_calls_synchronously(
        self, mock_select, mock_service_class, mock_get
    ):
        """Test sync_primary_selection=True calls select_primary_image synchronously."""
        # Mock PDF content
        mock_response = MagicMock()
        mock_response.content = b"fake pdf content"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        # Mock extraction service
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        # Create mock extracted figures
        img = Image.new("RGB", (500, 500), color="blue")
        buffer = BytesIO()
        img.save(buffer, format="JPEG")
        content_file = ContentFile(buffer.getvalue(), name="test-figure.jpg")
        mock_service.extract_figures_from_pdf.return_value = [content_file]
        mock_select.return_value = True

        result = extract_pdf_figures(self.paper.id, sync_primary_selection=True)

        self.assertTrue(result)
        mock_select.assert_called_once_with(
            self.paper.id,
            skip_feed_refresh_extraction_check=False,
        )

    @patch("paper.tasks.figure_tasks.requests.get")
    @patch("paper.tasks.figure_tasks.FigureExtractionService")
    @patch("paper.tasks.figure_tasks.select_primary_image")
    def test_sync_primary_selection_error_handling(
        self, mock_select, mock_service_class, mock_get
    ):
        """Test that sync primary selection errors don't break extraction."""
        # Mock PDF content
        mock_response = MagicMock()
        mock_response.content = b"fake pdf content"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        # Mock extraction service
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        # Create mock extracted figures
        img = Image.new("RGB", (500, 500), color="blue")
        buffer = BytesIO()
        img.save(buffer, format="JPEG")
        content_file = ContentFile(buffer.getvalue(), name="test-figure.jpg")
        mock_service.extract_figures_from_pdf.return_value = [content_file]

        # Make select_primary_image raise an exception
        mock_select.side_effect = Exception("Selection failed")

        result = extract_pdf_figures(self.paper.id, sync_primary_selection=True)

        # Extraction should still succeed even if selection fails
        self.assertTrue(result)
        mock_select.assert_called_once()

    @patch("paper.tasks.figure_tasks.requests.get")
    @patch("paper.tasks.figure_tasks.FigureExtractionService")
    @patch("paper.tasks.figure_tasks.select_primary_image.apply_async")
    def test_async_primary_selection_default(
        self, mock_select_async, mock_service_class, mock_get
    ):
        """Test that default behavior calls select_primary_image asynchronously."""
        # Mock PDF content
        mock_response = MagicMock()
        mock_response.content = b"fake pdf content"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        # Mock extraction service
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        # Create mock extracted figures
        img = Image.new("RGB", (500, 500), color="blue")
        buffer = BytesIO()
        img.save(buffer, format="JPEG")
        content_file = ContentFile(buffer.getvalue(), name="test-figure.jpg")
        mock_service.extract_figures_from_pdf.return_value = [content_file]

        result = extract_pdf_figures(self.paper.id)

        self.assertTrue(result)
        mock_select_async.assert_called_once_with(
            (self.paper.id,),
            {"skip_feed_refresh_extraction_check": False},
            priority=5,
        )
