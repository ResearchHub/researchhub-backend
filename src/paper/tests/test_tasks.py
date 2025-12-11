from io import BytesIO
from unittest.mock import MagicMock, patch

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from PIL import Image

from paper.constants.figure_selection_criteria import MIN_PRIMARY_SCORE_THRESHOLD
from paper.models import Figure
from paper.tasks import (
    create_download_url,
    create_pdf_screenshot,
    extract_pdf_figures,
    select_primary_image,
)
from paper.tests import helpers


class TestTasks(TestCase):

    @override_settings(SCRAPER_URL="https://scraper/?url={url}")
    def test_create_download_url(self):
        # Arrange
        test_cases = [
            (
                "https://arxiv.org/pdf/1234.56789.pdf",
                "arxiv",
                "https://scraper/?url=https%3A//arxiv.org/pdf/1234.56789.pdf",
            ),
            (
                "https://www.biorxiv.org/content/10.1101/2023.10.01.123456v1.full.pdf",
                "biorxiv",
                (
                    "https://scraper/?url=https%3A//www.biorxiv.org/"
                    "content/10.1101/2023.10.01.123456v1.full.pdf"
                ),
            ),
            (
                "https://www.example.com/paper.pdf",
                "chemrxiv",
                "https://www.example.com/paper.pdf",
            ),
        ]

        for url, source, expected in test_cases:
            with self.subTest(msg=f"Testing URL: {url} with source: {source}"):
                # Act
                result = create_download_url(url, source)

                # Assert
                self.assertEqual(result, expected)
                self.assertEqual(result, expected)
                self.assertEqual(result, expected)


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

        with patch("paper.tasks.extract_pdf_figures.apply_async") as mock_retry:
            result = extract_pdf_figures(paper.id)
            self.assertFalse(result)
            mock_retry.assert_called_once()

    @patch("paper.tasks.requests.get")
    @patch("paper.tasks.FigureExtractionService")
    @patch("paper.tasks.select_primary_image.apply_async")
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
        mock_select_task.assert_called_once_with((paper.id,), priority=5)

    @patch("paper.tasks.requests.get")
    @patch("paper.tasks.FigureExtractionService")
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

        with patch("paper.tasks.select_primary_image.apply_async"):
            result = extract_pdf_figures(paper.id)

        self.assertTrue(result)
        # Should not create duplicate
        final_count = Figure.objects.filter(
            paper=paper, figure_type=Figure.FIGURE
        ).count()
        self.assertEqual(final_count, initial_count, "Duplicate figure was created")

    @patch("paper.tasks.requests.get")
    @patch("paper.tasks.extract_pdf_figures.apply_async")
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

        with patch("paper.tasks.create_pdf_screenshot") as mock_create_preview:
            mock_create_preview.return_value = True
            result = select_primary_image(paper.id)

            self.assertTrue(result)
            mock_create_preview.assert_called_once_with(paper)

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

    @patch("paper.tasks.BedrockPrimaryImageService")
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

    @patch("paper.tasks.BedrockPrimaryImageService")
    @patch("paper.tasks.create_pdf_screenshot")
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
        mock_create_preview.assert_called_once_with(self.paper)

    @patch("paper.tasks.BedrockPrimaryImageService")
    @patch("paper.tasks.create_pdf_screenshot")
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
        mock_create_preview.assert_called_once_with(self.paper)

    @patch("paper.tasks.BedrockPrimaryImageService")
    @patch("paper.tasks.select_primary_image.apply_async")
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


class CreatePdfScreenshotTests(TestCase):
    """Test suite for create_pdf_screenshot helper function."""

    def setUp(self):
        """Set up test environment."""
        self.paper = helpers.create_paper(title="Test Paper")
        self.paper.file.name = "test.pdf"
        self.paper.save()

    @patch("paper.tasks.requests.get")
    @patch("paper.tasks.fitz")
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

    @patch("paper.tasks.requests.get")
    @patch("paper.tasks.fitz")
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
