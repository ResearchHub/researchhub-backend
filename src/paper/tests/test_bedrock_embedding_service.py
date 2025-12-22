import json
from unittest.mock import MagicMock, patch

from django.test import TestCase

from paper.services.bedrock_embedding_service import (
    MAX_INPUT_TEXT_LENGTH,
    BedrockEmbeddingService,
)
from paper.tests import helpers


class BedrockEmbeddingServiceTests(TestCase):
    """Test suite for BedrockEmbeddingService."""

    def setUp(self):
        """Set up test environment."""
        self.mock_create_client_patcher = patch(
            "paper.services.bedrock_embedding_service.create_client"
        )
        self.mock_create_client = self.mock_create_client_patcher.start()

        self.mock_client = MagicMock()
        self.mock_create_client.return_value = self.mock_client

        self.service = BedrockEmbeddingService()

    def tearDown(self):
        """Clean up patches."""
        self.mock_create_client_patcher.stop()

    def _mock_embedding_response(self, embedding):
        """Create a mock response from Bedrock embedding API."""
        response_body = json.dumps({"embedding": embedding})
        mock_body = MagicMock()
        mock_body.read.return_value = response_body.encode()
        return {"body": mock_body}

    def test_generate_embedding_success(self):
        """Test successful embedding generation."""
        expected_embedding = [0.1] * 1024
        self.mock_client.invoke_model.return_value = self._mock_embedding_response(
            expected_embedding
        )

        result = self.service.generate_embedding("Test text for embedding")

        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1024)
        self.assertEqual(result, expected_embedding)

        # Verify invoke_model was called correctly
        self.mock_client.invoke_model.assert_called_once()
        call_args = self.mock_client.invoke_model.call_args
        self.assertEqual(call_args.kwargs["modelId"], "amazon.titan-embed-text-v2:0")
        self.assertEqual(call_args.kwargs["contentType"], "application/json")

    def test_generate_embedding_empty_text(self):
        """Test that empty text returns None."""
        result = self.service.generate_embedding("")
        self.assertIsNone(result)

        result = self.service.generate_embedding("   ")
        self.assertIsNone(result)

    def test_generate_embedding_none_text(self):
        """Test that None text returns None."""
        result = self.service.generate_embedding(None)
        self.assertIsNone(result)

    def test_generate_embedding_truncates_long_text(self):
        """Test that text exceeding max length is truncated."""
        long_text = "a" * (MAX_INPUT_TEXT_LENGTH + 1000)
        expected_embedding = [0.5] * 1024
        self.mock_client.invoke_model.return_value = self._mock_embedding_response(
            expected_embedding
        )

        result = self.service.generate_embedding(long_text)

        self.assertIsNotNone(result)
        # Verify the text was truncated in the request
        call_args = self.mock_client.invoke_model.call_args
        request_body = json.loads(call_args.kwargs["body"])
        self.assertEqual(len(request_body["inputText"]), MAX_INPUT_TEXT_LENGTH)

    def test_generate_embedding_with_custom_dimensions(self):
        """Test embedding generation with custom dimensions."""
        expected_embedding = [0.2] * 512
        self.mock_client.invoke_model.return_value = self._mock_embedding_response(
            expected_embedding
        )

        result = self.service.generate_embedding("Test text", dimensions=512)

        self.assertIsNotNone(result)
        # Verify dimensions parameter was passed
        call_args = self.mock_client.invoke_model.call_args
        request_body = json.loads(call_args.kwargs["body"])
        self.assertEqual(request_body["dimensions"], 512)

    def test_generate_embedding_api_error(self):
        """Test that API errors are handled gracefully."""
        self.mock_client.invoke_model.side_effect = Exception("API Error")

        result = self.service.generate_embedding("Test text")

        self.assertIsNone(result)

    def test_generate_embedding_missing_embedding_in_response(self):
        """Test handling of response with missing embedding field."""
        response_body = json.dumps({"error": "some error"})
        mock_body = MagicMock()
        mock_body.read.return_value = response_body.encode()
        self.mock_client.invoke_model.return_value = {"body": mock_body}

        result = self.service.generate_embedding("Test text")

        self.assertIsNone(result)

    def test_generate_paper_embedding_with_title_only(self):
        """Test paper embedding with title only."""
        expected_embedding = [0.3] * 1024
        self.mock_client.invoke_model.return_value = self._mock_embedding_response(
            expected_embedding
        )

        result = self.service.generate_paper_embedding(title="Test Paper Title")

        self.assertIsNotNone(result)
        # Verify the text format
        call_args = self.mock_client.invoke_model.call_args
        request_body = json.loads(call_args.kwargs["body"])
        self.assertEqual(request_body["inputText"], "Title: Test Paper Title")

    def test_generate_paper_embedding_with_title_and_abstract(self):
        """Test paper embedding with title and abstract."""
        expected_embedding = [0.4] * 1024
        self.mock_client.invoke_model.return_value = self._mock_embedding_response(
            expected_embedding
        )

        result = self.service.generate_paper_embedding(
            title="Test Paper Title",
            abstract="This is the paper abstract describing the research.",
        )

        self.assertIsNotNone(result)
        # Verify the text format
        call_args = self.mock_client.invoke_model.call_args
        request_body = json.loads(call_args.kwargs["body"])
        expected_text = (
            "Title: Test Paper Title\n\n"
            "Abstract: This is the paper abstract describing the research."
        )
        self.assertEqual(request_body["inputText"], expected_text)

    def test_generate_paper_embedding_no_title(self):
        """Test that missing title returns None."""
        result = self.service.generate_paper_embedding(title="")
        self.assertIsNone(result)

        result = self.service.generate_paper_embedding(title=None)
        self.assertIsNone(result)

    def test_generate_paper_embedding_empty_abstract(self):
        """Test paper embedding with empty abstract falls back to title only."""
        expected_embedding = [0.5] * 1024
        self.mock_client.invoke_model.return_value = self._mock_embedding_response(
            expected_embedding
        )

        result = self.service.generate_paper_embedding(
            title="Test Paper Title", abstract=""
        )

        self.assertIsNotNone(result)
        call_args = self.mock_client.invoke_model.call_args
        request_body = json.loads(call_args.kwargs["body"])
        self.assertEqual(request_body["inputText"], "Title: Test Paper Title")

    def test_generate_paper_embedding_whitespace_abstract(self):
        """Test paper embedding with whitespace-only abstract falls back to title only."""
        expected_embedding = [0.5] * 1024
        self.mock_client.invoke_model.return_value = self._mock_embedding_response(
            expected_embedding
        )

        result = self.service.generate_paper_embedding(
            title="Test Paper Title", abstract="   "
        )

        self.assertIsNotNone(result)
        call_args = self.mock_client.invoke_model.call_args
        request_body = json.loads(call_args.kwargs["body"])
        self.assertEqual(request_body["inputText"], "Title: Test Paper Title")


class EmbeddingTasksTests(TestCase):
    """Test suite for embedding Celery tasks."""

    def setUp(self):
        """Set up test environment."""
        self.mock_service_patcher = patch(
            "paper.tasks.embedding_tasks.BedrockEmbeddingService"
        )
        self.mock_service_class = self.mock_service_patcher.start()
        self.mock_service = MagicMock()
        self.mock_service_class.return_value = self.mock_service

        # Mock the Celery signal processor to avoid Redis connection attempts
        self.mock_registry_patcher = patch(
            "search.celery.CelerySignalProcessor.registry_update_task"
        )
        self.mock_registry = self.mock_registry_patcher.start()
        self.mock_registry.apply_async = MagicMock()

        self.mock_related_patcher = patch(
            "search.celery.CelerySignalProcessor.registry_update_related_task"
        )
        self.mock_related = self.mock_related_patcher.start()
        self.mock_related.apply_async = MagicMock()

    def tearDown(self):
        """Clean up patches."""
        self.mock_service_patcher.stop()
        self.mock_registry_patcher.stop()
        self.mock_related_patcher.stop()

    def test_generate_paper_embedding_task_success(self):
        """Test successful embedding generation task."""
        from paper.tasks.embedding_tasks import generate_paper_embedding

        paper = helpers.create_paper(title="Test Paper", raw_authors=["Test Author"])
        paper.abstract = "This is a test abstract."
        paper.save()

        expected_embedding = [0.1] * 1024
        self.mock_service.generate_paper_embedding.return_value = expected_embedding

        result = generate_paper_embedding(paper.id)

        self.assertTrue(result)
        paper.refresh_from_db()
        self.assertEqual(paper.title_abstract_embedding, expected_embedding)

    def test_generate_paper_embedding_task_paper_not_found(self):
        """Test task handles non-existent paper gracefully."""
        from paper.tasks.embedding_tasks import generate_paper_embedding

        result = generate_paper_embedding(99999)

        self.assertFalse(result)

    def test_generate_paper_embedding_task_no_title(self):
        """Test task handles paper with no title."""
        from paper.tasks.embedding_tasks import generate_paper_embedding

        paper = helpers.create_paper(title="", raw_authors=[])
        paper.paper_title = None
        paper.save()

        result = generate_paper_embedding(paper.id)

        self.assertFalse(result)

    def test_generate_paper_embedding_task_uses_paper_title_first(self):
        """Test task prefers paper_title over title."""
        from paper.tasks.embedding_tasks import generate_paper_embedding

        paper = helpers.create_paper(title="User Title", raw_authors=["Test Author"])
        paper.paper_title = "Official Paper Title"
        paper.abstract = "Abstract"
        paper.save()

        expected_embedding = [0.2] * 1024
        self.mock_service.generate_paper_embedding.return_value = expected_embedding

        result = generate_paper_embedding(paper.id)

        self.assertTrue(result)
        self.mock_service.generate_paper_embedding.assert_called_once_with(
            title="Official Paper Title", abstract="Abstract"
        )

    def test_generate_embeddings_batch_success(self):
        """Test batch embedding generation."""
        from paper.tasks.embedding_tasks import generate_embeddings_batch

        paper1 = helpers.create_paper(title="Paper 1", raw_authors=[])
        paper2 = helpers.create_paper(title="Paper 2", raw_authors=[])

        expected_embedding = [0.3] * 1024
        self.mock_service.generate_paper_embedding.return_value = expected_embedding

        result = generate_embeddings_batch([paper1.id, paper2.id])

        self.assertEqual(result["processed"], 2)
        self.assertEqual(result["success"], 2)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["skipped"], 0)

    def test_generate_embeddings_batch_skips_existing(self):
        """Test batch skips papers with existing embeddings."""
        from paper.tasks.embedding_tasks import generate_embeddings_batch

        paper1 = helpers.create_paper(title="Paper 1", raw_authors=[])
        paper1.title_abstract_embedding = [0.1] * 1024
        paper1.save()

        paper2 = helpers.create_paper(title="Paper 2", raw_authors=[])

        expected_embedding = [0.3] * 1024
        self.mock_service.generate_paper_embedding.return_value = expected_embedding

        result = generate_embeddings_batch([paper1.id, paper2.id], skip_existing=True)

        self.assertEqual(result["processed"], 2)
        self.assertEqual(result["success"], 1)
        self.assertEqual(result["skipped"], 1)

    def test_generate_embeddings_batch_processes_existing_when_forced(self):
        """Test batch processes papers with existing embeddings when skip_existing=False."""
        from paper.tasks.embedding_tasks import generate_embeddings_batch

        paper = helpers.create_paper(title="Paper 1", raw_authors=[])
        paper.title_abstract_embedding = [0.1] * 1024
        paper.save()

        new_embedding = [0.9] * 1024
        self.mock_service.generate_paper_embedding.return_value = new_embedding

        result = generate_embeddings_batch([paper.id], skip_existing=False)

        self.assertEqual(result["success"], 1)
        self.assertEqual(result["skipped"], 0)
        paper.refresh_from_db()
        self.assertEqual(paper.title_abstract_embedding, new_embedding)
