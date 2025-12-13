from io import BytesIO
from unittest.mock import MagicMock, patch

from django.test import TestCase
from PIL import Image

from paper.services.figure_extraction_service import (
    MAX_FIGURE_HEIGHT,
    MAX_FIGURE_WIDTH,
    MIN_FIGURE_HEIGHT,
    MIN_FIGURE_WIDTH,
    FigureExtractionService,
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
            content_file = figures[0]
            # Verify the image was resized by checking its dimensions
            image = Image.open(content_file)
            width, height = image.size
            self.assertLessEqual(width, MAX_FIGURE_WIDTH)
            self.assertLessEqual(height, MAX_FIGURE_HEIGHT)

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
            content_file = figures[0]
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
            content_file = figures[0]
            # Verify the image dimensions
            image = Image.open(content_file)
            width, height = image.size
            self.assertEqual(width, 600)
            self.assertEqual(height, 600)

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

    def test_convert_to_rgb_rgba_image(self):
        """Test that RGBA images are converted to RGB with white background."""
        # Create an RGBA image with transparency
        rgba_image = Image.new("RGBA", (100, 100), color=(255, 0, 0, 128))
        result = self.service._convert_to_rgb(rgba_image)

        self.assertEqual(result.mode, "RGB")
        self.assertEqual(result.size, (100, 100))

    def test_convert_to_rgb_la_image(self):
        """Test that LA (grayscale with alpha) images are converted to RGB."""
        # Create an LA image
        la_image = Image.new("LA", (100, 100), color=(128, 200))
        result = self.service._convert_to_rgb(la_image)

        self.assertEqual(result.mode, "RGB")
        self.assertEqual(result.size, (100, 100))

    def test_convert_to_rgb_palette_image(self):
        """Test that P (palette) images are converted to RGB."""
        # Create a palette image
        palette = []
        for i in range(256):
            palette.extend([i, i, i])
        palette_image = Image.new("P", (100, 100))
        palette_image.putpalette(palette)
        result = self.service._convert_to_rgb(palette_image)

        self.assertEqual(result.mode, "RGB")
        self.assertEqual(result.size, (100, 100))

    def test_convert_to_rgb_already_rgb(self):
        """Test that RGB images are returned unchanged."""
        # Create an RGB image
        rgb_image = Image.new("RGB", (100, 100), color=(255, 0, 0))
        result = self.service._convert_to_rgb(rgb_image)

        self.assertEqual(result.mode, "RGB")
        self.assertEqual(result.size, (100, 100))
        self.assertEqual(result.size, rgb_image.size)
