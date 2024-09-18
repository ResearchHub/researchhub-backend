from unittest.mock import MagicMock, patch

from celery.exceptions import MaxRetriesExceededError, Retry
from django.test import TestCase, override_settings
from django.utils import timezone

from paper.models import Paper, PaperFetchLog
from paper.tasks import pull_new_openalex_works, pull_updated_openalex_works


class TestPullNewOpenAlexWorks(TestCase):
    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    @patch("paper.tasks.OpenAlex")
    @patch("paper.tasks.process_openalex_works")
    def test_pull_new_openalex_works_success(self, mock_process_works, mock_openalex):
        # Mock OpenAlex.get_works to return some test data
        mock_openalex_instance = mock_openalex.return_value
        mock_openalex_instance.get_works.side_effect = [
            ([{"id": "W1"}, {"id": "W2"}], "next_cursor_1"),
            ([{"id": "W3"}, {"id": "W4"}], "next_cursor_2"),
            ([], None),
        ]

        # Call the function
        pull_new_openalex_works.apply()

        # Check that get_works was called twice
        self.assertEqual(mock_openalex_instance.get_works.call_count, 3)

        # Check that process_openalex_works was called twice
        self.assertEqual(mock_process_works.call_count, 2)

        # Check that a PaperFetchLog was created and updated correctly
        log = PaperFetchLog.objects.latest("id")
        self.assertEqual(log.source, PaperFetchLog.OPENALEX)
        self.assertEqual(log.fetch_type, PaperFetchLog.FETCH_NEW)
        self.assertEqual(log.status, PaperFetchLog.SUCCESS)
        self.assertEqual(log.total_papers_processed, 4)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    @patch("paper.tasks.OpenAlex")
    @patch("paper.tasks.process_openalex_works")
    def test_pull_new_openalex_works_no_results(
        self, mock_process_works, mock_openalex
    ):
        # Mock OpenAlex.get_works to return no results
        mock_openalex_instance = mock_openalex.return_value
        mock_openalex_instance.get_works.return_value = ([], None)

        # Call the function
        pull_new_openalex_works.apply()

        # Check that get_works was called once
        mock_openalex_instance.get_works.assert_called_once()

        # Check that process_openalex_works was not called
        mock_process_works.assert_not_called()

        # Check that a PaperFetchLog was created and updated correctly
        log = PaperFetchLog.objects.latest("id")
        self.assertEqual(log.source, PaperFetchLog.OPENALEX)
        self.assertEqual(log.fetch_type, PaperFetchLog.FETCH_NEW)
        self.assertEqual(log.status, PaperFetchLog.SUCCESS)
        self.assertEqual(log.total_papers_processed, 0)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    @patch("paper.tasks.OpenAlex")
    @patch("paper.tasks.process_openalex_works")
    def test_pull_new_openalex_works_existing_pending_log(
        self, mock_process_works, mock_openalex
    ):
        # Create a pending log
        PaperFetchLog.objects.create(
            source=PaperFetchLog.OPENALEX,
            fetch_type=PaperFetchLog.FETCH_NEW,
            status=PaperFetchLog.PENDING,
            started_date=timezone.now(),
        )

        # Call the function
        pull_new_openalex_works.apply()

        # Check that get_works was not called
        mock_openalex.assert_not_called()

        # Check that process_openalex_works was not called
        mock_process_works.assert_not_called()

        # Check that no new PaperFetchLog was created
        self.assertEqual(PaperFetchLog.objects.count(), 1)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    @patch("paper.tasks.OpenAlex")
    @patch("paper.tasks.process_openalex_works")
    @patch("paper.tasks.pull_new_openalex_works.retry")
    def test_pull_new_openalex_works_failed_retry(
        self, mock_retry, mock_process_works, mock_openalex
    ):
        # Mock OpenAlex.get_works to always raise an exception
        mock_openalex_instance = mock_openalex.return_value
        mock_openalex_instance.get_works.side_effect = Exception("Test exception")

        # Mock the retry method to raise MaxRetriesExceededError on the 4th call
        mock_retry.side_effect = [Retry(), Retry(), Retry(), MaxRetriesExceededError()]

        # Create a PaperFetchLog
        paper_fetch_log = PaperFetchLog.objects.create(
            source=PaperFetchLog.OPENALEX,
            fetch_type=PaperFetchLog.FETCH_NEW,
            status=PaperFetchLog.PENDING,
        )

        # Call the task and expect it to raise Retry exceptions
        with self.assertRaises(Retry):
            pull_new_openalex_works(retry=0, paper_fetch_log_id=paper_fetch_log.id)
        with self.assertRaises(Retry):
            pull_new_openalex_works(retry=1, paper_fetch_log_id=paper_fetch_log.id)
        with self.assertRaises(Retry):
            pull_new_openalex_works(retry=2, paper_fetch_log_id=paper_fetch_log.id)

        # On the 4th attempt, it should raise the original exception (Test exception)
        with self.assertRaises(Exception) as cm:
            pull_new_openalex_works(retry=3, paper_fetch_log_id=paper_fetch_log.id)
        self.assertEqual(str(cm.exception), "Test exception")

        # Check that get_works was called 4 times
        self.assertEqual(mock_openalex_instance.get_works.call_count, 4)

        # Check that process_openalex_works was not called
        mock_process_works.assert_not_called()

        # Refresh the log from the database
        paper_fetch_log.refresh_from_db()

        # Check that the log status was updated to FAILED
        self.assertEqual(paper_fetch_log.status, PaperFetchLog.FAILED)
        self.assertEqual(paper_fetch_log.total_papers_processed, 0)
        self.assertIsNotNone(paper_fetch_log.completed_date)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    @patch("paper.tasks.OpenAlex")
    @patch("paper.tasks.process_openalex_works")
    def test_pull_new_openalex_works_successful_retry(
        self, mock_process_works, mock_openalex
    ):
        # Mock OpenAlex.get_works to raise an exception on the second call, then succeed
        mock_openalex_instance = mock_openalex.return_value
        mock_openalex_instance.get_works.side_effect = [
            Exception("Test exception"),
            ([{"id": "W1"}, {"id": "W2"}], "next_cursor_1"),
            ([{"id": "W3"}, {"id": "W4"}], "next_cursor_2"),
            ([], None),
        ]

        task = pull_new_openalex_works.s()
        task.retry = MagicMock(side_effect=Retry())

        with self.assertRaises(Retry):
            task.apply()

        paper_fetch_log = PaperFetchLog.objects.latest("id")
        result = task.apply(args=[1, paper_fetch_log.id])

        self.assertEqual(mock_openalex_instance.get_works.call_count, 4)
        self.assertEqual(mock_process_works.call_count, 2)

        log = PaperFetchLog.objects.latest("id")
        self.assertEqual(log.source, PaperFetchLog.OPENALEX)
        self.assertEqual(log.fetch_type, PaperFetchLog.FETCH_NEW)
        self.assertEqual(log.status, PaperFetchLog.SUCCESS)
        self.assertEqual(log.total_papers_processed, 4)

        self.assertTrue(result.successful())
        self.assertEqual(result.result, True)


class TestPullUpdatedOpenAlexWorks(TestCase):
    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    @patch("paper.tasks.OpenAlex")
    @patch("paper.tasks.process_openalex_works")
    def test_pull_updated_openalex_works_success(
        self, mock_process_works, mock_openalex
    ):
        # Mock OpenAlex.get_works to return some test data
        mock_openalex_instance = mock_openalex.return_value
        mock_openalex_instance.get_works.side_effect = [
            (
                [{"id": "W1", "doi": "10.1234/1"}, {"id": "W2", "doi": "10.1234/2"}],
                "next_cursor_1",
            ),
            (
                [{"id": "W3", "doi": "10.1234/3"}, {"id": "W4", "doi": "10.1234/4"}],
                "next_cursor_2",
            ),
            ([], None),
        ]

        # Call the function
        pull_updated_openalex_works.apply()

        # Check that get_works was called thrice
        self.assertEqual(mock_openalex_instance.get_works.call_count, 3)

        # Check that process_openalex_works was called twice
        self.assertEqual(mock_process_works.call_count, 2)

        # Check that a PaperFetchLog was created and updated correctly
        log = PaperFetchLog.objects.latest("id")
        self.assertEqual(log.source, PaperFetchLog.OPENALEX)
        self.assertEqual(log.fetch_type, PaperFetchLog.FETCH_UPDATE)
        self.assertEqual(log.status, PaperFetchLog.SUCCESS)
        self.assertEqual(log.total_papers_processed, 4)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    @patch("paper.tasks.OpenAlex")
    @patch("paper.tasks.process_openalex_works")
    def test_pull_updated_openalex_works_no_results(
        self, mock_process_works, mock_openalex
    ):
        # Mock OpenAlex.get_works to return no results
        mock_openalex_instance = mock_openalex.return_value
        mock_openalex_instance.get_works.return_value = ([], None)

        # Call the function
        pull_updated_openalex_works.apply()

        # Check that get_works was called once
        mock_openalex_instance.get_works.assert_called_once()

        # Check that process_openalex_works was not called
        mock_process_works.assert_not_called()

        # Check that a PaperFetchLog was created and updated correctly
        log = PaperFetchLog.objects.latest("id")
        self.assertEqual(log.source, PaperFetchLog.OPENALEX)
        self.assertEqual(log.fetch_type, PaperFetchLog.FETCH_UPDATE)
        self.assertEqual(log.status, PaperFetchLog.SUCCESS)
        self.assertEqual(log.total_papers_processed, 0)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    @patch("paper.tasks.OpenAlex")
    @patch("paper.tasks.process_openalex_works")
    def test_pull_updated_openalex_works_existing_pending_log(
        self, mock_process_works, mock_openalex
    ):
        # Create a pending log
        PaperFetchLog.objects.create(
            source=PaperFetchLog.OPENALEX,
            fetch_type=PaperFetchLog.FETCH_UPDATE,
            status=PaperFetchLog.PENDING,
            started_date=timezone.now(),
        )

        # Call the function
        pull_updated_openalex_works.apply()

        # Check that get_works was not called
        mock_openalex.assert_not_called()

        # Check that process_openalex_works was not called
        mock_process_works.assert_not_called()

        # Check that no new PaperFetchLog was created
        self.assertEqual(PaperFetchLog.objects.count(), 1)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    @patch("paper.tasks.OpenAlex")
    @patch("paper.tasks.process_openalex_works")
    @patch("paper.tasks.pull_updated_openalex_works.retry")
    def test_pull_updated_openalex_works_retry_and_fail(
        self, mock_retry, mock_process_works, mock_openalex
    ):
        # Mock OpenAlex.get_works to always raise an exception
        mock_openalex_instance = mock_openalex.return_value
        mock_openalex_instance.get_works.side_effect = Exception("Test exception")

        # Mock the retry method to raise MaxRetriesExceededError on the 4th call
        mock_retry.side_effect = [Retry(), Retry(), Retry(), MaxRetriesExceededError()]

        # Create a PaperFetchLog
        paper_fetch_log = PaperFetchLog.objects.create(
            source=PaperFetchLog.OPENALEX,
            fetch_type=PaperFetchLog.FETCH_UPDATE,
            status=PaperFetchLog.PENDING,
        )

        # Call the task and expect it to raise Retry exceptions
        with self.assertRaises(Retry):
            pull_updated_openalex_works(retry=0, paper_fetch_log_id=paper_fetch_log.id)
        with self.assertRaises(Retry):
            pull_updated_openalex_works(retry=1, paper_fetch_log_id=paper_fetch_log.id)
        with self.assertRaises(Retry):
            pull_updated_openalex_works(retry=2, paper_fetch_log_id=paper_fetch_log.id)

        # On the 4th attempt, it should raise the original exception (Test exception)
        with self.assertRaises(Exception) as cm:
            pull_updated_openalex_works(retry=3, paper_fetch_log_id=paper_fetch_log.id)
        self.assertEqual(str(cm.exception), "Test exception")

        # Check that get_works was called 4 times
        self.assertEqual(mock_openalex_instance.get_works.call_count, 4)

        # Check that process_openalex_works was not called
        mock_process_works.assert_not_called()

        # Refresh the log from the database
        paper_fetch_log.refresh_from_db()

        # Check that the log status was updated to FAILED
        self.assertEqual(paper_fetch_log.status, PaperFetchLog.FAILED)
        self.assertEqual(paper_fetch_log.total_papers_processed, 0)
        self.assertIsNotNone(paper_fetch_log.completed_date)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    @patch("paper.tasks.OpenAlex")
    @patch("paper.tasks.process_openalex_works")
    def test_pull_updated_openalex_works_successful_retry(
        self, mock_process_works, mock_openalex
    ):
        # Mock OpenAlex.get_works to raise an exception on the second call, then succeed
        mock_openalex_instance = mock_openalex.return_value
        mock_openalex_instance.get_works.side_effect = [
            Exception("Test exception"),
            ([{"id": "W1"}, {"id": "W2"}], "next_cursor_1"),
            ([{"id": "W3"}, {"id": "W4"}], "next_cursor_2"),
            ([], None),
        ]

        task = pull_updated_openalex_works.s()
        task.retry = MagicMock(side_effect=Retry())

        with self.assertRaises(Retry):
            task.apply()

        paper_fetch_log = PaperFetchLog.objects.latest("id")
        result = task.apply(args=[1, paper_fetch_log.id])

        self.assertEqual(mock_openalex_instance.get_works.call_count, 4)
        self.assertEqual(mock_process_works.call_count, 2)

        log = PaperFetchLog.objects.latest("id")
        self.assertEqual(log.source, PaperFetchLog.OPENALEX)
        self.assertEqual(log.fetch_type, PaperFetchLog.FETCH_UPDATE)
        self.assertEqual(log.status, PaperFetchLog.SUCCESS)
        self.assertEqual(log.total_papers_processed, 4)

        self.assertTrue(result.successful())
        self.assertEqual(result.result, True)
