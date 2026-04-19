from unittest.mock import patch

from django.test import SimpleTestCase

from ai_peer_review.tasks import process_proposal_review_task, process_rfp_summary_task


class AIPeerReviewTaskTests(SimpleTestCase):
    # Patch names on ``tasks`` — that module binds ``run_*`` at import time, so
    # patching ``services.*.run_*`` would not replace the task's reference.
    @patch("ai_peer_review.tasks.run_proposal_review")
    def test_process_proposal_review_task_delegates(self, mock_run):
        process_proposal_review_task.run(901)
        mock_run.assert_called_once_with(901)

    @patch("ai_peer_review.tasks.run_rfp_summary")
    def test_process_rfp_summary_task_delegates(self, mock_run):
        process_rfp_summary_task.run(902)
        mock_run.assert_called_once_with(902)
