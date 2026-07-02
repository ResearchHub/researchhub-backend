"""Unit tests for ``ProposalRunState`` -- plateau tracking, best-round
snapshots, and the failure-reason taxonomy, exercised without Django."""

import unittest

from research_ai.services.agent import (
    AgentRunError,
    IncompleteTurnError,
    IterationLimitError,
)
from research_ai.services.proposal_draft.config import ProposalDraftConfig
from research_ai.services.proposal_draft.run_state import ProposalRunState


def _build_config(**overrides) -> ProposalDraftConfig:
    defaults = {"max_rounds": 4, "plateau_patience": 2, "max_iterations": 50}
    defaults.update(overrides)
    return ProposalDraftConfig(**defaults)


def _build_report(overall, *, ok=False, rollup=None) -> dict:
    return {
        "panel": {"ok": ok, "overall": overall, "rollup": rollup or {}},
        "gaps": [] if ok else ["gap"],
    }


class ProposalRunStatePlateauTests(unittest.TestCase):
    def test_improvement_resets_counter_and_captures_best(self):
        # Arrange
        state = ProposalRunState(_build_config())
        first_submission = {"plain_text": "v1"}
        second_submission = {"plain_text": "v2"}

        # Act
        state.begin_round(first_submission)
        first_report = _build_report(3.0)
        state.record_gate_result(False, first_report)
        state.track_plateau(first_report)
        state.begin_round(second_submission)
        second_report = _build_report(3.5)
        state.record_gate_result(False, second_report)
        state.track_plateau(second_report)

        # Assert
        self.assertEqual(state.best_overall, 3.5)
        self.assertEqual(state.rounds_since_improvement, 0)
        self.assertIs(state.best_submission, second_submission)
        self.assertEqual(state.best_round, 2)

    def test_regression_counts_against_patience_and_keeps_earlier_best(self):
        # Arrange
        state = ProposalRunState(_build_config())
        peak_submission = {"plain_text": "peak"}

        # Act
        state.begin_round(peak_submission)
        peak_report = _build_report(4.0)
        state.record_gate_result(False, peak_report)
        state.track_plateau(peak_report)
        for text in ("worse-1", "worse-2"):
            state.begin_round({"plain_text": text})
            report = _build_report(3.2)
            state.record_gate_result(False, report)
            state.track_plateau(report)

        # Assert
        self.assertEqual(state.best_overall, 4.0)
        self.assertEqual(state.rounds_since_improvement, 2)
        self.assertIs(state.best_submission, peak_submission)
        self.assertEqual(state.best_round, 1)

    def test_non_numeric_overall_is_ignored(self):
        # Arrange
        state = ProposalRunState(_build_config())
        state.begin_round({"plain_text": "v1"})

        # Act
        state.track_plateau(_build_report(None))

        # Assert
        self.assertIsNone(state.best_overall)
        self.assertEqual(state.rounds_since_improvement, 0)
        self.assertIsNone(state.best_submission)

    def test_panel_plateaued_requires_patience_and_a_failing_panel(self):
        # Arrange
        state = ProposalRunState(_build_config(plateau_patience=2))
        state.rounds_since_improvement = 2

        # Act & Assert: a passing panel is never a plateau, whatever the counter.
        self.assertFalse(state.panel_plateaued(_build_report(4.8, ok=True)))
        self.assertTrue(state.panel_plateaued(_build_report(3.0)))
        state.rounds_since_improvement = 1
        self.assertFalse(state.panel_plateaued(_build_report(3.0)))


class ProposalRunStateOutcomeTests(unittest.TestCase):
    def test_persisted_outcome_prefers_the_best_round(self):
        # Arrange
        state = ProposalRunState(_build_config())
        state.begin_round({"plain_text": "peak"})
        peak_report = _build_report(4.0, rollup={"overall": 4.0})
        state.record_gate_result(False, peak_report)
        state.track_plateau(peak_report)
        state.begin_round({"plain_text": "regressed"})
        last_report = _build_report(3.0, rollup={"overall": 3.0})
        state.record_gate_result(False, last_report)
        state.track_plateau(last_report)

        # Act
        submission, gate_report, scores = state.persisted_outcome()

        # Assert
        self.assertEqual(submission, {"plain_text": "peak"})
        self.assertIs(gate_report, peak_report)
        self.assertEqual(scores, {"overall": 4.0})

    def test_persisted_outcome_falls_back_to_the_last_submission(self):
        # Arrange
        state = ProposalRunState(_build_config())
        state.begin_round({"plain_text": "unscored"})
        report = _build_report(None)
        state.record_gate_result(False, report)

        # Act
        submission, gate_report, _scores = state.persisted_outcome()

        # Assert
        self.assertEqual(submission, {"plain_text": "unscored"})
        self.assertIs(gate_report, report)

    def test_persisted_outcome_when_the_agent_never_submitted(self):
        # Arrange
        state = ProposalRunState(_build_config())

        # Act
        submission, gate_report, scores = state.persisted_outcome()

        # Assert
        self.assertEqual(submission, {})
        self.assertEqual(gate_report, {})
        self.assertEqual(scores, {})


class ProposalRunStateFailureMessageTests(unittest.TestCase):
    def test_gate_crash_takes_precedence(self):
        # Arrange
        state = ProposalRunState(_build_config())
        state.rounds_used = 2
        state.gate_crash = "boom"
        state.panel_unavailable = True

        # Act & Assert
        self.assertEqual(state.failure_message(), "gate check crashed on round 2: boom")

    def test_panel_unavailable(self):
        # Arrange
        state = ProposalRunState(_build_config())
        state.rounds_used = 1
        state.panel_unavailable = True

        # Act & Assert
        self.assertEqual(
            state.failure_message(),
            "judge panel unavailable (no judge returned a score) on round 1",
        )

    def test_agent_died_before_submitting_names_the_real_cause(self):
        # Arrange
        state = ProposalRunState(_build_config())
        state.record_agent_error(AgentRunError("throttled", iterations=3))

        # Act & Assert
        self.assertIn("provider error", state.failure_message())
        self.assertIn("throttled", state.failure_message())

    def test_no_submission_is_a_give_up(self):
        # Arrange
        state = ProposalRunState(_build_config())

        # Act & Assert
        self.assertEqual(state.failure_message(), "agent did not submit a proposal")

    def test_plateau_message_carries_the_numbers(self):
        # Arrange
        state = ProposalRunState(_build_config(plateau_patience=2))
        state.submitted = {"plain_text": "x"}
        state.rounds_used = 3
        state.best_overall = 3.5
        state.rounds_since_improvement = 2
        state.stopped_on_plateau = True

        # Act & Assert
        self.assertEqual(
            state.failure_message(),
            "panel score plateaued at 3.5 for 2 rounds below the 4.5 bar; "
            "stopped after 3 of 4 rounds",
        )

    def test_round_budget_exhausted(self):
        # Arrange
        state = ProposalRunState(_build_config(max_rounds=4))
        state.submitted = {"plain_text": "x"}
        state.rounds_used = 4

        # Act & Assert
        self.assertEqual(state.failure_message(), "gates not cleared within 4 rounds")

    def test_iteration_cap(self):
        # Arrange
        state = ProposalRunState(_build_config(max_iterations=50))
        state.submitted = {"plain_text": "x"}
        state.rounds_used = 2
        state.record_agent_error(IterationLimitError("cap", iterations=50))

        # Act & Assert
        self.assertIn("50-iteration cap", state.failure_message())
        self.assertIn("2 of 4 rounds", state.failure_message())

    def test_incomplete_turn_after_a_submit(self):
        # Arrange
        state = ProposalRunState(_build_config())
        state.submitted = {"plain_text": "x"}
        state.rounds_used = 2
        state.record_agent_error(
            IncompleteTurnError("stopped", stop_reason="max_tokens", iterations=7)
        )

        # Act & Assert
        self.assertEqual(
            state.failure_message(),
            "model stopped mid-run (max_tokens) after 2 rounds",
        )
        self.assertEqual(state.agent_iterations, 7)


if __name__ == "__main__":
    unittest.main()
