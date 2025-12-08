"""
Tests for figure extraction and primary image selection.
"""

import base64
from io import BytesIO
from unittest.mock import Mock, patch

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from paper.models import Figure, Paper
from paper.services.figure_extraction_service import FigureExtractionService
from paper.tests.helpers import create_paper
from paper.tests.test_tasks import TestTasks


class TestFigureExtractionService(TestCase):
    """Test the figure extraction service."""

    def setUp(self):
        """Set up test fixtures."""
        self.service = FigureExtractionService()
        self.paper = create_paper()

    def test_extract_figures_filters_by_minimum_size(self):
        """Test that figures below minimum size are filtered out."""
        # Create a small test PDF with embedded images
        # This would require a test PDF file, so we'll mock the extraction
        # In real tests, you'd use an actual PDF file
        
        # For now, test the filtering logic
        from PIL import Image
        
        # Create a small image (below 600x600 threshold)
        small_img = Image.new("RGB", (100, 100), color="red")
        img_buffer = BytesIO()
        small_img.save(img_buffer, format="PNG")
        
        # The service should filter this out
        # This is tested indirectly through integration tests
        
    @patch("paper.services.figure_extraction_service.fitz.open")
    def test_extract_figures_filters_by_aspect_ratio(self, mock_fitz_open):
        """Test that extreme aspect ratios are filtered out."""
        # Mock PDF document
        mock_doc = Mock()
        mock_page = Mock()
        
        # Mock image extraction
        mock_doc.extract_image.return_value = {
            "image": b"fake_image_data",
            "ext": "png",
        }
        
        # This test would need more setup with actual PDF structure
        # For now, it's a placeholder showing the test structure


class TestExtractPdfFiguresTask(TestTasks):
    """Test the extract_pdf_figures Celery task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("paper.tasks.extract_pdf_figures.select_primary_image")
    @patch("paper.services.figure_extraction_service.FigureExtractionService")
    def test_extract_pdf_figures_creates_figures(self, mock_service_class, mock_select):
        """Test that extract_pdf_figures creates Figure objects."""
        # Arrange
        paper = create_paper()
        
        # Create a mock PDF file
        pdf_content = b"fake_pdf_content"
        paper.file.save("test.pdf", ContentFile(pdf_content))
        paper.save()
        
        # Mock the extraction service
        mock_service = Mock()
        mock_service.extract_figures_from_pdf.return_value = [
            (ContentFile(b"image1", name="test-1.png"), {"width": 800, "height": 600}),
            (ContentFile(b"image2", name="test-2.png"), {"width": 700, "height": 700}),
        ]
        mock_service_class.return_value = mock_service
        
        # Mock requests.get for file URL
        with patch("paper.tasks.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.content = pdf_content
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response
            
            # Act
            from paper.tasks import extract_pdf_figures
            
            result = extract_pdf_figures(paper.id)
            
            # Assert
            self.assertTrue(result)
            self.assertEqual(Figure.objects.filter(paper=paper, figure_type=Figure.FIGURE).count(), 2)
            mock_select.apply_async.assert_called_once()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_extract_pdf_figures_handles_missing_file(self):
        """Test that extract_pdf_figures handles missing PDF file."""
        # Arrange
        paper = create_paper()
        # Don't create a file
        
        # Act
        from paper.tasks import extract_pdf_figures
        
        result = extract_pdf_figures(paper.id)
        
        # Assert
        self.assertFalse(result)
        self.assertEqual(Figure.objects.filter(paper=paper).count(), 0)


class TestSelectPrimaryImageTask(TestTasks):
    """Test the select_primary_image Celery task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("paper.services.bedrock_primary_image_service.BedrockPrimaryImageService")
    def test_select_primary_image_updates_is_primary(self, mock_service_class):
        """Test that select_primary_image sets is_primary flag."""
        # Arrange
        paper = create_paper()
        
        # Create test figures
        figure1 = Figure.objects.create(
            paper=paper,
            figure_type=Figure.FIGURE,
            file=ContentFile(b"image1", name="test1.png"),
        )
        figure2 = Figure.objects.create(
            paper=paper,
            figure_type=Figure.FIGURE,
            file=ContentFile(b"image2", name="test2.png"),
        )
        
        # Mock Bedrock service
        mock_service = Mock()
        mock_service.select_primary_image.return_value = figure2.id
        mock_service_class.return_value = mock_service
        
        # Act
        from paper.tasks import select_primary_image
        
        result = select_primary_image(paper.id)
        
        # Assert
        self.assertTrue(result)
        figure1.refresh_from_db()
        figure2.refresh_from_db()
        self.assertFalse(figure1.is_primary)
        self.assertTrue(figure2.is_primary)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_select_primary_image_handles_no_figures(self):
        """Test that select_primary_image handles papers with no figures."""
        # Arrange
        paper = create_paper()
        
        # Act
        from paper.tasks import select_primary_image
        
        result = select_primary_image(paper.id)
        
        # Assert
        self.assertFalse(result)

