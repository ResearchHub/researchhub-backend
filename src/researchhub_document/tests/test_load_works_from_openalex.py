from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from paper.models import Paper, PaperFetchLog
from user.related_models.author_model import Author


class LoadWorksFromOpenAlexTest(TestCase):
    @patch(
        "researchhub_document.management.commands.load_works_from_openalex.process_backfill_batch"
    )
    def test_backfill_mode(self, mock_process_backfill_batch):
        call_command("load_works_from_openalex", mode="backfill", start_id=1, to_id=3)

        mock_process_backfill_batch.assert_called_once()

    @patch(
        "researchhub_document.management.commands.load_works_from_openalex.process_openalex_work"
    )
    def test_fetch_mode_single_work(self, mock_process_openalex_work):
        call_command("load_works_from_openalex", mode="fetch", openalex_id="W123456789")

        mock_process_openalex_work.assert_called_once()

    @patch(
        "researchhub_document.management.commands.load_works_from_openalex.process_author_batch"
    )
    def test_fetch_mode_author_works(self, mock_process_author_batch):
        call_command(
            "load_works_from_openalex",
            mode="fetch",
            openalex_author_id="A123456789",
            journal="BIORXIV",
        )

        mock_process_author_batch.assert_called_once()

    @patch(
        "researchhub_document.management.commands.load_works_from_openalex.process_batch"
    )
    def test_fetch_mode_batch(self, mock_process_batch):
        call_command("load_works_from_openalex", mode="fetch", journal="BIORXIV")

        mock_process_batch.assert_called_once()

    @patch("researchhub_document.management.commands.load_works_from_openalex.OpenAlex")
    @patch(
        "researchhub_document.management.commands.load_works_from_openalex.process_openalex_works"
    )
    def test_process_batch(self, mock_process_openalex_works, mock_openalex):
        mock_openalex_instance = MagicMock()
        mock_openalex_instance.get_works.side_effect = [
            ([{"id": "W1"}, {"id": "W2"}], "next_cursor"),
            ([{"id": "W3"}], None),
        ]
        mock_openalex.return_value = mock_openalex_instance

        from researchhub_document.management.commands.load_works_from_openalex import (
            process_batch,
        )

        process_batch(mock_openalex_instance, "BIORXIV")

        self.assertEqual(mock_process_openalex_works.call_count, 2)
        self.assertEqual(PaperFetchLog.objects.count(), 1)
        fetch_log = PaperFetchLog.objects.first()
        self.assertEqual(fetch_log.status, PaperFetchLog.SUCCESS)
        self.assertEqual(fetch_log.total_papers_processed, 3)
        self.assertEqual(fetch_log.journal, "BIORXIV")

    @patch("researchhub_document.management.commands.load_works_from_openalex.OpenAlex")
    @patch(
        "researchhub_document.management.commands.load_works_from_openalex.process_openalex_works"
    )
    def test_process_author_batch(self, mock_process_openalex_works, mock_openalex):
        mock_openalex_instance = MagicMock()
        mock_openalex_instance.get_works.side_effect = [
            ([{"id": "W1"}, {"id": "W2"}], "next_cursor"),
            ([{"id": "W3"}], None),
        ]
        mock_openalex.return_value = mock_openalex_instance

        author = Author.objects.create()
        author.openalex_ids = ["https://openalex.org/A123456789"]
        author.save()

        from researchhub_document.management.commands.load_works_from_openalex import (
            process_author_batch,
        )

        process_author_batch(mock_openalex_instance, "A123456789", "BIORXIV")

        self.assertEqual(mock_process_openalex_works.call_count, 2)
        author.refresh_from_db()
        self.assertIsNotNone(author.last_full_fetch_from_openalex)

    @patch("researchhub_document.management.commands.load_works_from_openalex.OpenAlex")
    @patch(
        "researchhub_document.management.commands.load_works_from_openalex.process_openalex_works"
    )
    def test_pending_fetch_blocks_subsequent_call(
        self, mock_process_openalex_works, mock_openalex
    ):
        # Create a pending fetch log
        PaperFetchLog.objects.create(
            journal="BIORXIV",
            status=PaperFetchLog.PENDING,
            source=PaperFetchLog.OPENALEX,
        )

        mock_openalex_instance = MagicMock()
        mock_openalex.return_value = mock_openalex_instance

        call_command("load_works_from_openalex", mode="fetch", journal="BIORXIV")

        # Verify that get_works was not called on the OpenAlex instance
        mock_openalex_instance.get_works.assert_not_called()

        # Verify that process_openalex_works was not called
        mock_process_openalex_works.assert_not_called()

        # Verify that only one fetch log exists (the pending one we created)
        self.assertEqual(PaperFetchLog.objects.count(), 1)
        self.assertEqual(PaperFetchLog.objects.first().status, PaperFetchLog.PENDING)
