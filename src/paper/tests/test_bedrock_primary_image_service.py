import base64
from io import BytesIO
from unittest.mock import MagicMock, patch

from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image

from paper.models import Figure
from paper.services.bedrock_primary_image_service import (
    MAX_IMAGES_PER_BEDROCK_REQUEST,
    BedrockPrimaryImageService,
)
from paper.tests import helpers

test_storage = FileSystemStorage()


@patch.object(Figure._meta.get_field("file"), "storage", test_storage)
@patch.object(Figure._meta.get_field("thumbnail"), "storage", test_storage)
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

        # Mock Bedrock Converse API response with Tool Use
        mock_response = {
            "output": {
                "message": {
                    "content": [
                        {
                            "toolUse": {
                                "name": "evaluate_figures",
                                "input": {
                                    "selected_figure_index": 0,
                                    "scores": {
                                        "figure_0": 75.5,
                                        "figure_1": 65.0,
                                    },
                                },
                            }
                        }
                    ]
                }
            }
        }
        mock_client.converse.return_value = mock_response

        # Create new service instance to use mocked client
        service = BedrockPrimaryImageService()

        selected_id, score = service._select_best_from_batch(
            [figure1, figure2], "Test Title", "Test Abstract"
        )

        self.assertEqual(selected_id, figure1.id)
        self.assertEqual(score, 75.5)

    @patch("paper.services.bedrock_primary_image_service.create_client")
    def test_select_best_from_batch_tool_use_response(self, mock_create_client):
        """Test parsing Tool Use response from Converse API."""
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        figure1 = self._create_test_figure()
        figure2 = self._create_test_figure()

        # Mock Converse API response with Tool Use
        mock_response = {
            "output": {
                "message": {
                    "content": [
                        {
                            "toolUse": {
                                "name": "evaluate_figures",
                                "input": {
                                    "selected_figure_index": 1,
                                    "scores": {
                                        "figure_0": 70.0,
                                        "figure_1": 80.0,
                                    },
                                },
                            }
                        }
                    ]
                }
            }
        }
        mock_client.converse.return_value = mock_response

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

        # Mock Bedrock Converse API response
        mock_response = {
            "output": {
                "message": {
                    "content": [
                        {
                            "toolUse": {
                                "name": "evaluate_figures",
                                "input": {
                                    "selected_figure_index": 0,
                                    "scores": {
                                        "figure_0": 75.0,
                                        "figure_1": 65.0,
                                    },
                                },
                            }
                        }
                    ]
                }
            }
        }

        self.mock_client.converse.return_value = mock_response

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

        # Mock responses for batches using Converse API format
        def mock_converse(modelId, system, messages, toolConfig, inferenceConfig):
            selected_index = 0
            # Create scores for all figures in the batch
            # Each figure has image + text, so divide by 2
            num_figures = len(messages[0]["content"]) // 2
            scores = {
                f"figure_{i}": 70.0 if i == selected_index else 60.0
                for i in range(num_figures)
            }

            return {
                "output": {
                    "message": {
                        "content": [
                            {
                                "toolUse": {
                                    "name": "evaluate_figures",
                                    "input": {
                                        "selected_figure_index": selected_index,
                                        "scores": scores,
                                    },
                                }
                            }
                        ]
                    }
                }
            }

        mock_client.converse.side_effect = mock_converse

        service = BedrockPrimaryImageService()

        selected_id, score = service.select_primary_image(
            "Test Title", "Test Abstract", figures
        )

        # Should return a valid selection
        self.assertIsNotNone(selected_id)
        self.assertIsNotNone(score)
        # Should have called Bedrock multiple times (for batches and final selection)
        self.assertGreater(mock_client.converse.call_count, 1)

    @patch("paper.services.bedrock_primary_image_service.create_client")
    def test_select_best_from_batch_missing_tool_use(self, mock_create_client):
        """Test handling when Tool Use response is missing."""
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        figure1 = self._create_test_figure()
        figure2 = self._create_test_figure()

        # Mock response without tool use
        mock_response = {
            "output": {
                "message": {"content": [{"type": "text", "text": "Some text response"}]}
            }
        }
        mock_client.converse.return_value = mock_response

        service = BedrockPrimaryImageService()

        selected_id, score = service._select_best_from_batch(
            [figure1, figure2], "Test Title", "Test Abstract"
        )

        self.assertIsNone(selected_id)
        self.assertIsNone(score)

    @patch("paper.services.bedrock_primary_image_service.create_client")
    def test_select_best_from_batch_missing_output(self, mock_create_client):
        """Test handling when output is missing from response."""
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        figure1 = self._create_test_figure()

        # Mock response without output
        mock_response = {}
        mock_client.converse.return_value = mock_response

        service = BedrockPrimaryImageService()

        selected_id, score = service._select_best_from_batch(
            [figure1], "Test Title", "Test Abstract"
        )

        self.assertIsNone(selected_id)
        self.assertIsNone(score)
