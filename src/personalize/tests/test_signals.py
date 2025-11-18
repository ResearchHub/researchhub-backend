from unittest.mock import patch

from django.test import TestCase

from paper.models import Paper
from researchhub_document.models import ResearchhubUnifiedDocument


class PaperSignalTests(TestCase):
    @patch("personalize.signals.paper_signals.sync_paper_to_personalize_task")
    def test_signal_queues_task_on_paper_creation(self, mock_task):
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", is_removed=False
        )

        paper = Paper.objects.create(
            title="New Test Paper",
            paper_title="New Test Paper",
            unified_document=unified_doc,
            external_source="test",
        )

        mock_task.delay.assert_called_once_with(paper.id)

    @patch("personalize.signals.paper_signals.sync_paper_to_personalize_task")
    def test_signal_skips_on_paper_update(self, mock_task):
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", is_removed=False
        )

        paper = Paper.objects.create(
            title="Test Paper",
            paper_title="Test Paper",
            unified_document=unified_doc,
            external_source="test",
        )

        mock_task.reset_mock()

        paper.title = "Updated Title"
        paper.save()

        mock_task.delay.assert_not_called()

    @patch("personalize.signals.paper_signals.sync_paper_to_personalize_task")
    def test_signal_skips_paper_without_unified_doc(self, mock_task):
        paper = Paper.objects.create(
            title="Paper Without Unified Doc",
            paper_title="Paper Without Unified Doc",
            external_source="test",
            unified_document=None,
        )

        mock_task.delay.assert_not_called()
