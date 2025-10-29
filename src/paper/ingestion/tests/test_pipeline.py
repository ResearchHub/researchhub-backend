from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.utils import timezone

from paper.ingestion.constants import IngestionSource
from paper.ingestion.exceptions import FetchError, RetryExhaustedError
from paper.ingestion.pipeline import (
    IngestionStatus,
    PaperIngestionPipeline,
    fetch_all_papers,
    fetch_papers_from_source,
    process_batch_task,
)
from paper.models import PaperFetchLog


class TestIngestionStatus(TestCase):
    def test_initialization(self):
        """
        Test IngestionStatus initialization with defaults.
        """
        # Arrange & Act
        status = IngestionStatus(
            source="arxiv",
            start_time=timezone.now(),
        )

        # Assert
        self.assertEqual(status.source, "arxiv")
        self.assertIsNotNone(status.start_time)
        self.assertIsNone(status.end_time)
        self.assertEqual(status.total_fetched, 0)
        self.assertEqual(status.total_processed, 0)
        self.assertEqual(status.total_created, 0)
        self.assertEqual(status.total_updated, 0)
        self.assertEqual(status.total_errors, 0)
        self.assertEqual(status.errors, [])

    def test_to_dict(self):
        """
        Test to_dict method returns proper dictionary.
        """
        # Arrange
        start_time = timezone.now()
        end_time = start_time + timedelta(hours=1)

        status = IngestionStatus(
            source="biorxiv",
            start_time=start_time,
            end_time=end_time,
            total_fetched=100,
            total_processed=95,
            total_created=80,
            total_updated=15,
            total_errors=5,
            errors=[{"type": "parse_error", "message": "Invalid XML"}],
        )

        # Act
        result = status.to_dict()

        # Assert
        self.assertIsInstance(result, dict)
        self.assertEqual(result["source"], "biorxiv")
        self.assertEqual(result["total_fetched"], 100)
        self.assertEqual(result["total_processed"], 95)
        self.assertEqual(result["total_created"], 80)
        self.assertEqual(result["total_updated"], 15)
        self.assertEqual(result["total_errors"], 5)
        self.assertEqual(len(result["errors"]), 1)


class TestPaperIngestionPipeline(TestCase):
    def setUp(self):
        self.mock_arxiv_client = MagicMock()
        self.mock_biorxiv_client = MagicMock()

        self.clients = {
            "arxiv": self.mock_arxiv_client,
            "biorxiv": self.mock_biorxiv_client,
        }

        self.pipeline = PaperIngestionPipeline(self.clients)

    @patch("paper.ingestion.pipeline.process_batch_task")
    def test_run_ingestion_single_source(self, mock_process_batch):
        """
        Test ingestion for a single source.
        """
        # Arrange
        mock_papers = [
            {"id": "arxiv:2301.00001", "title": "Paper 1"},
            {"id": "arxiv:2301.00002", "title": "Paper 2"},
        ]
        self.mock_arxiv_client.fetch_recent.return_value = mock_papers

        since = timezone.now() - timedelta(days=1)
        until = timezone.now()

        # Act
        results = self.pipeline.run_ingestion(
            sources=["arxiv"],
            since=since,
            until=until,
        )

        # Assert
        self.assertIn("arxiv", results)
        status = results["arxiv"]
        self.assertEqual(status.source, "arxiv")
        self.assertEqual(status.total_fetched, 2)
        self.assertIsNotNone(status.end_time)

        # Verify client was called
        self.mock_arxiv_client.fetch_recent.assert_called_once_with(
            since=since,
            until=until,
        )

        # Verify batch processing was triggered
        mock_process_batch.delay.assert_called_once()

    @patch("paper.ingestion.pipeline.process_batch_task")
    def test_run_ingestion_with_create_fetch_log_true(self, mock_process_batch):
        """
        Test ingestion with create_fetch_log=True creates log entry.
        """
        # Arrange
        mock_papers = [
            {"id": "arxiv:2301.00001", "title": "Paper 1"},
            {"id": "arxiv:2301.00002", "title": "Paper 2"},
        ]
        self.mock_arxiv_client.fetch_recent.return_value = mock_papers

        # Act
        results = self.pipeline.run_ingestion(
            sources=["arxiv"],
            create_fetch_log=True,
        )

        # Assert
        self.assertIn("arxiv", results)
        status = results["arxiv"]
        self.assertEqual(status.total_fetched, 2)

        # Verify that a fetch log was created
        log = PaperFetchLog.objects.filter(source="ARXIV").order_by("-id").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, PaperFetchLog.SUCCESS)
        self.assertEqual(log.total_papers_processed, 2)

    @patch("paper.ingestion.pipeline.process_batch_task")
    def test_run_ingestion_with_create_fetch_log_false(self, mock_process_batch):
        """
        Test ingestion with create_fetch_log=False does not create log entry.
        """
        # Arrange
        mock_papers = [
            {"id": "arxiv:2301.00001", "title": "Paper 1"},
        ]
        self.mock_arxiv_client.fetch_recent.return_value = mock_papers

        # Get initial count
        initial_count = PaperFetchLog.objects.filter(source="ARXIV").count()

        # Act
        results = self.pipeline.run_ingestion(
            sources=["arxiv"],
            create_fetch_log=False,
        )

        # Assert
        self.assertIn("arxiv", results)
        status = results["arxiv"]
        self.assertEqual(status.total_fetched, 1)

        # Verify that no fetch log was created
        final_count = PaperFetchLog.objects.filter(source="ARXIV").count()
        self.assertEqual(initial_count, final_count)

    @patch("paper.ingestion.pipeline.process_batch_task")
    def test_run_ingestion_multiple_sources(self, mock_process_batch):
        """
        Test ingestion for multiple sources.
        """
        # Arrange
        arxiv_papers = [{"id": "arxiv:2301.00001", "title": "ArXiv Paper"}]
        biorxiv_papers = [
            {"id": "biorxiv:2301.00001", "title": "BioRxiv Paper 1"},
            {"id": "biorxiv:2301.00002", "title": "BioRxiv Paper 2"},
        ]

        self.mock_arxiv_client.fetch_recent.return_value = arxiv_papers
        self.mock_biorxiv_client.fetch_recent.return_value = biorxiv_papers

        # Act
        results = self.pipeline.run_ingestion()

        # Assert
        self.assertEqual(len(results), 2)
        self.assertIn("arxiv", results)
        self.assertIn("biorxiv", results)

        self.assertEqual(results["arxiv"].total_fetched, 1)
        self.assertEqual(results["biorxiv"].total_fetched, 2)

        # Verify both clients were called
        self.mock_arxiv_client.fetch_recent.assert_called_once()
        self.mock_biorxiv_client.fetch_recent.assert_called_once()

    @patch("paper.ingestion.pipeline.process_batch_task")
    def test_run_ingestion_with_fetch_error(self, mock_process_batch):
        """
        Test ingestion handles fetch errors properly.
        """
        # Arrange
        self.mock_arxiv_client.fetch_recent.side_effect = FetchError("API unavailable")

        # Act
        results = self.pipeline.run_ingestion(sources=["arxiv"])

        # Assert
        status = results["arxiv"]
        self.assertEqual(status.total_fetched, 0)
        self.assertIsNotNone(status.end_time)
        self.assertGreater(len(status.errors), 0)

        # Verify no batch processing was triggered
        mock_process_batch.delay.assert_not_called()

    @patch("paper.ingestion.pipeline.process_batch_task")
    def test_run_ingestion_unknown_source(self, mock_process_batch):
        """
        Test ingestion skips unknown sources.
        """
        # Arrange & Act
        results = self.pipeline.run_ingestion(sources=["unknown_source"])

        # Assert
        self.assertNotIn("unknown_source", results)
        mock_process_batch.delay.assert_not_called()

    @patch("paper.ingestion.pipeline.process_batch_task")
    def test_batch_processing(self, mock_process_batch):
        """
        Test papers are processed in correct batch sizes.
        """
        # Arrange

        # Create 75 mock papers (should result in 3 batches of 25)
        mock_papers = [
            {"id": f"arxiv:2301.{i:05d}", "title": f"Paper {i}"} for i in range(75)
        ]
        self.mock_arxiv_client.fetch_recent.return_value = mock_papers

        # Act
        results = self.pipeline.run_ingestion(sources=["arxiv"])

        # Assert
        self.assertIn("arxiv", results)
        status = results["arxiv"]
        self.assertEqual(status.source, "arxiv")
        self.assertEqual(status.total_fetched, 75)
        self.assertIsNotNone(status.end_time)

        # Verify correct number of batches
        self.assertEqual(mock_process_batch.delay.call_count, 3)

        # Verify batch sizes
        calls = mock_process_batch.delay.call_args_list
        batch_1 = calls[0][0][1]
        batch_2 = calls[1][0][1]
        batch_3 = calls[2][0][1]

        self.assertEqual(len(batch_1), 25)
        self.assertEqual(len(batch_2), 25)
        self.assertEqual(len(batch_3), 25)

    def test_get_last_fetch_time_with_existing_log(self):
        """
        Test getting last fetch time when log exists.
        """
        # Arrange
        completed_date = timezone.now() - timedelta(hours=6)
        PaperFetchLog.objects.create(
            source="ARXIV",
            fetch_type=PaperFetchLog.FETCH_UPDATE,
            status=PaperFetchLog.SUCCESS,
            started_date=completed_date - timedelta(minutes=10),
            completed_date=completed_date,
            total_papers_processed=50,
        )

        # Act
        last_fetch = self.pipeline._get_last_fetch_time("arxiv")

        # Assert
        # Should return the completed_date from the log
        expected = completed_date
        self.assertAlmostEqual(
            last_fetch,
            expected,
            delta=timedelta(seconds=1),
        )

    def test_get_last_fetch_time_without_log(self):
        """
        Test getting last fetch time when no log exists.
        """
        # Arrange & Act
        # Get last fetch time
        last_fetch = self.pipeline._get_last_fetch_time("chemrxiv")

        # Assert
        expected = timezone.now() - timedelta(days=1)
        self.assertAlmostEqual(
            last_fetch,
            expected,
            delta=timedelta(seconds=10),
        )

    def test_log_fetch_success(self):
        """
        Test logging successful fetch.
        """
        # Arrange
        status = IngestionStatus(
            source="arxiv",
            start_time=timezone.now() - timedelta(minutes=5),
            end_time=timezone.now(),
            total_fetched=100,
        )

        # Act
        self.pipeline._log_fetch("arxiv", status, success=True)

        # Assert
        # Verify log was created
        log = PaperFetchLog.objects.filter(source="ARXIV").order_by("-id").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, PaperFetchLog.SUCCESS)
        self.assertEqual(log.total_papers_processed, 100)

    def test_log_fetch_failure(self):
        """
        Test logging failed fetch.
        """
        # Arrange
        status = IngestionStatus(
            source="biorxiv",
            start_time=timezone.now() - timedelta(minutes=5),
            end_time=timezone.now(),
            total_fetched=0,
            errors=[{"type": "api_error", "message": "Connection timeout"}],
        )

        # Act
        self.pipeline._log_fetch("biorxiv", status, success=False)

        # Assert
        # Verify log was created
        log = PaperFetchLog.objects.filter(source="BIORXIV").order_by("-id").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, PaperFetchLog.FAILED)
        self.assertEqual(log.total_papers_processed, 0)

    @patch("paper.ingestion.pipeline.process_batch_task")
    def test_empty_paper_list(self, mock_process_batch):
        """
        Test handling empty paper list from source.
        """
        # Arrange
        self.mock_arxiv_client.fetch_recent.return_value = []

        # Act
        results = self.pipeline.run_ingestion(sources=["arxiv"])

        # Assert
        status = results["arxiv"]
        self.assertEqual(status.total_fetched, 0)
        self.assertEqual(len(status.errors), 0)

        # No batches should be processed
        mock_process_batch.delay.assert_not_called()

    @patch("paper.ingestion.pipeline.process_batch_task")
    def test_retry_exhausted_error(self, mock_process_batch):
        """
        Test handling retry exhausted error.
        """
        # Arrange
        self.mock_arxiv_client.fetch_recent.side_effect = RetryExhaustedError(
            "Max retries reached"
        )

        # Act
        results = self.pipeline.run_ingestion(sources=["arxiv"])

        # Assert
        status = results["arxiv"]
        self.assertEqual(status.total_fetched, 0)
        self.assertGreater(len(status.errors), 0)
        self.assertEqual(status.errors[0]["type"], "fetch_error")


@override_settings(PAPER_INGESTION_ENABLED=True)
class TestPaperIngestionTasks(TestCase):
    """
    Test cases for Celery tasks.
    """

    @patch("paper.ingestion.pipeline.PaperIngestionPipeline")
    @patch("paper.ingestion.pipeline.ClientFactory.create_client")
    def test_fetch_papers_from_source_arxiv(
        self, mock_create_client, mock_pipeline_class
    ):
        """
        Test fetch_papers_from_source task for ArXiv.
        """
        # Arrange
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        mock_pipeline = MagicMock()
        mock_pipeline.run_ingestion.return_value = {
            "arxiv": IngestionStatus(
                source="arxiv",
                start_time=timezone.now(),
                end_time=timezone.now(),
                total_fetched=10,
            )
        }
        mock_pipeline_class.return_value = mock_pipeline

        # Act
        result = fetch_papers_from_source("arxiv")

        # Assert
        # Verify ClientFactory was called to create the client
        mock_create_client.assert_called_once_with(IngestionSource.ARXIV)

        # Verify pipeline was created with the mocked client
        mock_pipeline_class.assert_called_once_with({"arxiv": mock_client})
        mock_pipeline.run_ingestion.assert_called_once()

        self.assertEqual(result["source"], "arxiv")
        self.assertEqual(result["total_fetched"], 10)

    @override_settings(PAPER_INGESTION_ENABLED=False)
    def test_fetch_all_papers_disabled(self):
        """
        Test fetch_all_papers when ingestion is disabled.
        """
        # Act
        result = fetch_all_papers()

        # Assert
        self.assertEqual(result, {})

    @patch("paper.ingestion.pipeline.group")
    def test_fetch_all_papers(self, mock_group):
        """
        Test fetch_all_papers orchestrator task.
        """
        # Arrange
        mock_job = MagicMock()
        mock_job.id = "test-job-id"
        mock_group.return_value.delay.return_value = mock_job

        # Act
        result = fetch_all_papers()

        # Assert
        self.assertEqual(result["status"], "initiated")
        self.assertEqual(result["sources"], ["arxiv", "biorxiv", "chemrxiv", "medrxiv"])
        self.assertEqual(result["job_id"], "test-job-id")

    def test_process_batch_task(self):
        """
        Test process_batch_task.
        """
        # Arrange
        batch = [
            {"id": "test-1", "title": "Test Paper 1"},
            {"id": "test-2", "title": "Test Paper 2"},
        ]

        # Act
        result = process_batch_task("arxiv", batch)

        # Assert
        self.assertEqual(result["source"], "arxiv")
        self.assertEqual(result["batch_size"], 2)
        self.assertIn("created", result)
        self.assertEqual(result["source"], "arxiv")
        self.assertEqual(result["batch_size"], 2)
        self.assertIn("created", result)
