"""
Tests for FigureExtractionService.
"""

from io import BytesIO
from unittest.mock import MagicMock, patch

from django.test import TestCase
from PIL import Image

from paper.services.figure_extraction_service import (
    FigureExtractionService,
    MAX_FIGURE_HEIGHT,
    MAX_FIGURE_WIDTH,
    MIN_FIGURE_HEIGHT,
    MIN_FIGURE_WIDTH,
)
from paper.tests import helpers


class FigureExtractionServiceTests(TestCase):
    """Test suite for FigureExtractionService."""

    def setUp(self):
        """Set up test environment."""
        self.service = FigureExtractionService()
        self.paper = helpers.create_paper(title="Test Paper")

    def _create_test_image(self, width=500, height=500, format="PNG"):
        """Create a test image in memory."""
        img = Image.new("RGB", (width, height), color="red")
        buffer = BytesIO()
        img.save(buffer, format=format)
        return buffer.getvalue()

    def test_extract_figures_filters_small_images(self):
        """Test that images smaller than minimum size are filtered out."""
        # Create a small image (below minimum size)
        small_image = self._create_test_image(
            width=MIN_FIGURE_WIDTH - 100, height=MIN_FIGURE_HEIGHT - 100
        )

        # Mock PyMuPDF to return the small image
        with patch("paper.services.figure_extraction_service.fitz") as mock_fitz:
            mock_doc = MagicMock()
            mock_page = MagicMock()
            mock_fitz.open.return_value = mock_doc
            mock_doc.__iter__.return_value = [mock_page]

            # Mock image extraction
            mock_page.get_images.return_value = [(0,)]
            mock_doc.extract_image.return_value = {
                "image": small_image,
                "ext": "png",
            }

            figures = self.service.extract_figures_from_pdf(b"fake pdf", self.paper.id)

            # Should filter out the small image
            self.assertEqual(len(figures), 0)

    def test_extract_figures_filters_extreme_aspect_ratios(self):
        """Test that images with extreme aspect ratios are filtered out."""
        # Create a very wide image (aspect ratio > 3:1)
        wide_image = self._create_test_image(width=1000, height=200)

        with patch("paper.services.figure_extraction_service.fitz") as mock_fitz:
            mock_doc = MagicMock()
            mock_page = MagicMock()
            mock_fitz.open.return_value = mock_doc
            mock_doc.__iter__.return_value = [mock_page]

            mock_page.get_images.return_value = [(0,)]
            mock_doc.extract_image.return_value = {"image": wide_image, "ext": "png"}

            figures = self.service.extract_figures_from_pdf(b"fake pdf", self.paper.id)

            # Should filter out the extreme aspect ratio image
            self.assertEqual(len(figures), 0)

    def test_extract_figures_resizes_large_images(self):
        """Test that images larger than maximum size are resized."""
        # Create a large image (exceeds maximum size)
        large_image = self._create_test_image(
            width=MAX_FIGURE_WIDTH + 500, height=MAX_FIGURE_HEIGHT + 500
        )

        with patch("paper.services.figure_extraction_service.fitz") as mock_fitz:
            mock_doc = MagicMock()
            mock_page = MagicMock()
            mock_fitz.open.return_value = mock_doc
            mock_doc.__iter__.return_value = [mock_page]

            mock_page.get_images.return_value = [(0,)]
            mock_doc.extract_image.return_value = {"image": large_image, "ext": "png"}

            figures = self.service.extract_figures_from_pdf(b"fake pdf", self.paper.id)

            # Should extract and resize the image
            self.assertEqual(len(figures), 1)
            content_file, metadata = figures[0]
            self.assertLessEqual(metadata["width"], MAX_FIGURE_WIDTH)
            self.assertLessEqual(metadata["height"], MAX_FIGURE_HEIGHT)
            self.assertTrue(metadata["resized"])

    def test_extract_figures_converts_to_jpeg(self):
        """Test that images are converted to JPEG format."""
        # Create a PNG image
        png_image = self._create_test_image(width=500, height=500, format="PNG")

        with patch("paper.services.figure_extraction_service.fitz") as mock_fitz:
            mock_doc = MagicMock()
            mock_page = MagicMock()
            mock_fitz.open.return_value = mock_doc
            mock_doc.__iter__.return_value = [mock_page]

            mock_page.get_images.return_value = [(0,)]
            mock_doc.extract_image.return_value = {"image": png_image, "ext": "png"}

            figures = self.service.extract_figures_from_pdf(b"fake pdf", self.paper.id)

            # Should extract and convert to JPEG
            self.assertEqual(len(figures), 1)
            content_file, metadata = figures[0]
            # Check that filename ends with .jpg
            self.assertTrue(content_file.name.endswith(".jpg"))

    def test_extract_figures_handles_valid_image(self):
        """Test that valid images are extracted successfully."""
        # Create a valid image (within size limits, reasonable aspect ratio)
        valid_image = self._create_test_image(width=600, height=600)

        with patch("paper.services.figure_extraction_service.fitz") as mock_fitz:
            mock_doc = MagicMock()
            mock_page = MagicMock()
            mock_fitz.open.return_value = mock_doc
            mock_doc.__iter__.return_value = [mock_page]

            mock_page.get_images.return_value = [(0,)]
            mock_doc.extract_image.return_value = {"image": valid_image, "ext": "png"}

            figures = self.service.extract_figures_from_pdf(b"fake pdf", self.paper.id)

            # Should extract the valid image
            self.assertEqual(len(figures), 1)
            content_file, metadata = figures[0]
            self.assertEqual(metadata["width"], 600)
            self.assertEqual(metadata["height"], 600)
            self.assertFalse(metadata["resized"])

    def test_extract_figures_handles_multiple_pages(self):
        """Test that figures are extracted from multiple pages."""
        valid_image = self._create_test_image(width=600, height=600)

        with patch("paper.services.figure_extraction_service.fitz") as mock_fitz:
            mock_doc = MagicMock()
            mock_page1 = MagicMock()
            mock_page2 = MagicMock()
            mock_fitz.open.return_value = mock_doc
            mock_doc.__iter__.return_value = [mock_page1, mock_page2]

            mock_page1.get_images.return_value = [(0,)]
            mock_page2.get_images.return_value = [(1,)]
            mock_doc.extract_image.side_effect = [
                {"image": valid_image, "ext": "png"},
                {"image": valid_image, "ext": "png"},
            ]

            figures = self.service.extract_figures_from_pdf(b"fake pdf", self.paper.id)

            # Should extract figures from both pages
            self.assertEqual(len(figures), 2)

    def test_extract_figures_handles_rgba_images(self):
        """Test that RGBA images are converted to RGB."""
        # Create an RGBA image
        rgba_image = Image.new("RGBA", (500, 500), color=(255, 0, 0, 128))
        buffer = BytesIO()
        rgba_image.save(buffer, format="PNG")
        rgba_bytes = buffer.getvalue()

        with patch("paper.services.figure_extraction_service.fitz") as mock_fitz:
            mock_doc = MagicMock()
            mock_page = MagicMock()
            mock_fitz.open.return_value = mock_doc
            mock_doc.__iter__.return_value = [mock_page]

            mock_page.get_images.return_value = [(0,)]
            mock_doc.extract_image.return_value = {"image": rgba_bytes, "ext": "png"}

            figures = self.service.extract_figures_from_pdf(b"fake pdf", self.paper.id)

            # Should convert RGBA to RGB and extract
            self.assertEqual(len(figures), 1)

    def test_extract_figures_handles_errors_gracefully(self):
        """Test that errors during extraction are handled gracefully."""
        with patch("paper.services.figure_extraction_service.fitz") as mock_fitz:
            mock_doc = MagicMock()
            mock_page = MagicMock()
            mock_fitz.open.return_value = mock_doc
            mock_doc.__iter__.return_value = [mock_page]

            # Simulate an error during image extraction
            mock_page.get_images.side_effect = Exception("Extraction error")

            # Should not raise an exception
            figures = self.service.extract_figures_from_pdf(b"fake pdf", self.paper.id)
            self.assertEqual(len(figures), 0)

