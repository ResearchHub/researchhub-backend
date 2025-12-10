import base64
import json
from io import BytesIO
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image

from paper.models import Figure
from paper.services.bedrock_primary_image_service import (
    MAX_IMAGES_PER_BEDROCK_REQUEST,
    BedrockPrimaryImageService,
)
from paper.tests import helpers


class BedrockPrimaryImageServiceTests(TestCase):
    """Test suite for BedrockPrimaryImageService."""

    def setUp(self):
        """Set up test environment."""
        self.mock_create_client_patcher = patch(
            "paper.services.bedrock_primary_image_service.create_client"
        )
        self.mock_create_client = self.mock_create_client_patcher.start()

        mock_client = MagicMock()
        self.mock_create_client.return_value = mock_client

        self.service = BedrockPrimaryImageService()
        self.paper = helpers.create_paper(
            title="Test Paper", raw_authors=["Test Author"]
        )
        self.mock_client = mock_client

    def tearDown(self):
        """Clean up patches."""
        self.mock_create_client_patcher.stop()

    def _create_test_figure(
        self, paper=None, is_primary=False, figure_type=Figure.FIGURE
    ):
        """Create a test figure."""
        if paper is None:
            paper = self.paper

        # Create a simple test image
        img = Image.new("RGB", (500, 500), color="blue")
        buffer = BytesIO()
        img.save(buffer, format="JPEG")
        image_file = SimpleUploadedFile(
            "test_figure.jpg", buffer.getvalue(), content_type="image/jpeg"
        )

        figure = Figure.objects.create(
            paper=paper,
            figure_type=figure_type,
            is_primary=is_primary,
            file=image_file,
        )
        return figure

    def test_encode_image_to_base64_success(self):
        """Test successful image encoding to base64."""
        figure = self._create_test_figure()

        result = self.service._encode_image_to_base64(figure)

        self.assertIsNotNone(result)
        base64_image, media_type = result
        self.assertEqual(media_type, "image/jpeg")
        # Verify it's valid base64
        decoded = base64.b64decode(base64_image)
        self.assertGreater(len(decoded), 0)

    def test_encode_image_to_base64_no_file(self):
        """Test encoding fails gracefully when figure has no file."""
        figure = Figure.objects.create(
            paper=self.paper, figure_type=Figure.FIGURE, file=None
        )

        result = self.service._encode_image_to_base64(figure)

        self.assertIsNone(result)

    def test_resize_and_compress_for_bedrock_large_dimension(self):
        """Test that images exceeding dimension limits are resized."""
        # Create a large image (exceeds 8000px limit)
        large_image = Image.new("RGB", (10000, 10000), color="red")
        buffer = BytesIO()
        large_image.save(buffer, format="JPEG", quality=95)
        image_bytes = buffer.getvalue()

        figure = self._create_test_figure()
        result = self.service._resize_and_compress_for_bedrock(image_bytes, figure.id)

        # Should be resized
        result_image = Image.open(BytesIO(result))
        self.assertLessEqual(result_image.width, 8000)
        self.assertLessEqual(result_image.height, 8000)

    def test_resize_and_compress_for_bedrock_large_file_size(self):
        """Test that images exceeding file size limits are compressed."""
        # Create a high-quality image that might exceed size limit
        large_image = Image.new("RGB", (5000, 5000), color="red")
        buffer = BytesIO()
        large_image.save(buffer, format="JPEG", quality=100)
        image_bytes = buffer.getvalue()

        figure = self._create_test_figure()
        result = self.service._resize_and_compress_for_bedrock(image_bytes, figure.id)

        # Should be compressed to under 4.5MB
        self.assertLess(len(result), 4.5 * 1024 * 1024)

    def test_resize_and_compress_for_bedrock_rgba_conversion(self):
        """Test that RGBA images are converted to RGB."""
        rgba_image = Image.new("RGBA", (500, 500), color=(255, 0, 0, 128))
        buffer = BytesIO()
        rgba_image.save(buffer, format="PNG")
        rgba_bytes = buffer.getvalue()

        figure = self._create_test_figure()
        result = self.service._resize_and_compress_for_bedrock(rgba_bytes, figure.id)

        # Should be converted to RGB (JPEG)
        result_image = Image.open(BytesIO(result))
        self.assertEqual(result_image.mode, "RGB")

    def test_build_prompt_includes_criteria(self):
        """Test that the prompt includes all scoring criteria."""
        prompt = self.service._build_prompt(
            "Test Title", "Test Abstract", num_figures=3
        )

        # Check that key criteria are mentioned
        self.assertIn("Scientific Impact", prompt)
        self.assertIn("Social Media Potential", prompt)
        self.assertIn("Visual Quality", prompt)
        self.assertIn("Test Title", prompt)
        self.assertIn("Test Abstract", prompt)

    @patch("paper.services.bedrock_primary_image_service.create_client")
    def test_select_best_from_batch_success(self, mock_create_client):
        """Test successful selection from a batch."""
        # Create mock Bedrock client
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        # Create test figures
        figure1 = self._create_test_figure()
        figure2 = self._create_test_figure()

        # Mock Bedrock response
        response_data = json.dumps(
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "selected_figure_index": 0,
                                "scores": {
                                    "figure_0": {
                                        "total_score": 75.5,
                                        "scientific_impact": 80,
                                        "visual_quality": 70,
                                    },
                                    "figure_1": {
                                        "total_score": 65.0,
                                        "scientific_impact": 70,
                                        "visual_quality": 60,
                                    },
                                },
                                "reasoning": "Figure 0 is better",
                            }
                        ),
                    }
                ]
            }
        ).encode()
        mock_response = {"body": BytesIO(response_data)}
        mock_client.invoke_model.return_value = mock_response

        # Create new service instance to use mocked client
        service = BedrockPrimaryImageService()

        selected_id, score = service._select_best_from_batch(
            [figure1, figure2], "Test Title", "Test Abstract"
        )

        self.assertEqual(selected_id, figure1.id)
        self.assertEqual(score, 75.5)

    @patch("paper.services.bedrock_primary_image_service.create_client")
    def test_select_best_from_batch_json_in_markdown(self, mock_create_client):
        """Test parsing JSON from markdown code blocks."""
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        figure1 = self._create_test_figure()
        figure2 = self._create_test_figure()

        # Mock response with JSON in markdown
        response_text = (
            "```json\n"
            + json.dumps(
                {
                    "selected_figure_index": 1,
                    "scores": {
                        "figure_1": {"total_score": 80.0},
                    },
                }
            )
            + "\n```"
        )
        response_data = json.dumps(
            {"content": [{"type": "text", "text": response_text}]}
        ).encode()
        mock_response = {"body": BytesIO(response_data)}
        mock_client.invoke_model.return_value = mock_response

        service = BedrockPrimaryImageService()

        selected_id, score = service._select_best_from_batch(
            [figure1, figure2], "Test Title", "Test Abstract"
        )

        self.assertEqual(selected_id, figure2.id)
        self.assertEqual(score, 80.0)

    @patch("paper.services.bedrock_primary_image_service.create_client")
    def test_select_best_from_batch_empty_batch(self, mock_create_client):
        """Test handling of empty batch."""
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        service = BedrockPrimaryImageService()

        selected_id, score = service._select_best_from_batch(
            [], "Test Title", "Test Abstract"
        )

        self.assertIsNone(selected_id)
        self.assertIsNone(score)

    @patch("paper.services.bedrock_primary_image_service.create_client")
    def test_select_best_from_batch_exceeds_limit(self, mock_create_client):
        """Test that batches exceeding limit are rejected."""
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        # Create more figures than the limit
        figures = [
            self._create_test_figure()
            for _ in range(MAX_IMAGES_PER_BEDROCK_REQUEST + 1)
        ]

        service = BedrockPrimaryImageService()

        selected_id, score = service._select_best_from_batch(
            figures, "Test Title", "Test Abstract"
        )

        self.assertIsNone(selected_id)
        self.assertIsNone(score)

    def test_select_primary_image_single_batch(self):
        """Test selection when figures fit in single batch."""
        self.mock_client.reset_mock()

        figure1 = self._create_test_figure()
        figure2 = self._create_test_figure()

        # Mock Bedrock response
        response_data = json.dumps(
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "selected_figure_index": 0,
                                "scores": {
                                    "figure_0": {"total_score": 75.0},
                                },
                            }
                        ),
                    }
                ]
            }
        ).encode()

        self.mock_client.invoke_model.return_value = {"body": BytesIO(response_data)}

        service = BedrockPrimaryImageService()

        selected_id, score = service.select_primary_image(
            "Test Title", "Test Abstract", [figure1, figure2]
        )

        self.assertEqual(selected_id, figure1.id)
        self.assertEqual(score, 75.0)

    @patch("paper.services.bedrock_primary_image_service.create_client")
    def test_select_primary_image_batching(self, mock_create_client):
        """Test selection with batching for many figures."""
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        # Create more figures than the batch limit
        figures = [
            self._create_test_figure()
            for _ in range(MAX_IMAGES_PER_BEDROCK_REQUEST + 5)
        ]

        # Mock responses for batches
        def mock_invoke_model(modelId, body):
            selected_index = 0

            response_data = json.dumps(
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "selected_figure_index": selected_index,
                                    "scores": {
                                        f"figure_{selected_index}": {
                                            "total_score": 70.0
                                        },
                                    },
                                }
                            ),
                        }
                    ]
                }
            ).encode()
            return {"body": BytesIO(response_data)}

        mock_client.invoke_model.side_effect = mock_invoke_model

        service = BedrockPrimaryImageService()

        selected_id, score = service.select_primary_image(
            "Test Title", "Test Abstract", figures
        )

        # Should return a valid selection
        self.assertIsNotNone(selected_id)
        self.assertIsNotNone(score)
        # Should have called Bedrock multiple times (for batches and final selection)
        self.assertGreater(mock_client.invoke_model.call_count, 1)
