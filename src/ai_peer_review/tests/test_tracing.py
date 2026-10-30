"""Each review's LLM calls share a Braintrust trace tagged with the review id."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from ai_peer_review.services import proposal_review_service
from ai_peer_review.services.proposal_key_insights_service import (
    ProposalKeyInsightsService,
)
from research_ai.services import tracing_service


class ProposalReviewTracingTests(SimpleTestCase):
    def _trace(self, run, target, attribute):
        context = MagicMock()
        calls = []
        context.__enter__.side_effect = lambda: calls.append("enter")
        context.__exit__.side_effect = lambda *_: calls.append("exit")
        with (
            patch.object(tracing_service, "_trace_logger", MagicMock()),
            patch.object(
                tracing_service.braintrust, "start_span", return_value=context
            ) as start,
            patch.object(
                target, attribute, side_effect=lambda *a, **k: calls.append("run")
            ),
        ):
            run()
        return start, calls

    def test_review_runs_inside_a_span_tagged_with_the_review(self):
        # Arrange / Act
        start, calls = self._trace(
            lambda: proposal_review_service.run_proposal_review(42),
            proposal_review_service,
            "_run_proposal_review",
        )

        # Assert
        start.assert_called_once_with(
            name="ai_peer_review.proposal_review",
            type="task",
            metadata={"review_id": 42},
        )
        self.assertEqual(calls, ["enter", "run", "exit"])

    def test_key_insights_run_inside_a_span_tagged_with_the_review(self):
        # Arrange / Act
        start, calls = self._trace(
            lambda: ProposalKeyInsightsService(llm=MagicMock()).run(42, force=True),
            ProposalKeyInsightsService,
            "_run",
        )

        # Assert
        start.assert_called_once_with(
            name="ai_peer_review.key_insights",
            type="task",
            metadata={"review_id": 42},
        )
        self.assertEqual(calls, ["enter", "run", "exit"])
