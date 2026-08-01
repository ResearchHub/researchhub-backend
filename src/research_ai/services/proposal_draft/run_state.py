"""Loop-state bookkeeping for one proposal-drafting run.

``ProposalRunState`` is the runner's memory of how the run has gone: rounds
spent, the latest submission and gate report, how the core agent terminated,
the panel-score plateau counters, and a snapshot of the best-scoring round.
It is pure bookkeeping over plain dicts and counters -- no persistence, no
agent, no tools -- so the trickiest run logic (plateau detection and the
failure-reason taxonomy in ``failure_message``) is testable in isolation.

The runner mutates this as rounds complete; the ``DraftRecorder`` reads it to
persist outcomes.
"""

from research_ai.services.agent import (
    AgentRunError,
    IncompleteTurnError,
    IterationLimitError,
)
from research_ai.services.proposal_draft.config import ProposalDraftConfig


class ProposalRunState:
    """Mutable state of one bounded proposal-drafting loop."""

    def __init__(self, config: ProposalDraftConfig):
        self.config = config

        # Loop state captured by the submit handler / gate runner.
        self.rounds_used = 0
        self.accepted = False
        self.submitted: dict | None = None
        self.last_gate_report: dict = {}
        self.final_scores: dict = {}

        # How the core agent terminated (filled after ``agent.run``
        # returns/raises) -- feeds the specific failure message a FAILED run
        # records. ``agent_error`` carries the detail (provider error text,
        # truncation stop reason) for that message.
        self.agent_stop_reason: str | None = None
        self.agent_error: str | None = None

        # Infrastructure failures the submit handler contains: a crashed gate
        # check or an empty judge panel ends the run with its real cause
        # instead of letting the model revise against a broken referee.
        self.gate_crash: str | None = None
        self.panel_unavailable = False
        # Why every judge dropped out (truncated turn, provider error, ...), so
        # the recorded failure names the cause and not just the symptom.
        self.panel_error: str | None = None

        # Panel-score plateau tracking.
        self.best_overall: float | None = None
        self.rounds_since_improvement = 0
        self.stopped_on_plateau = False

        # Snapshot of the highest-scoring round so a FAILED run persists the
        # best draft the agent reached, not merely the last -- a plateau can
        # stop the loop on a round that regressed below an earlier peak.
        self.best_submission: dict | None = None
        self.best_gate_report: dict = {}
        self.best_scores: dict = {}

        # Snapshot of the highest-scoring round that cleared EVERY gate (panel
        # over the bar plus the mechanical gates). Clearing the bar is the floor
        # for shipping, not a stop signal -- the loop keeps trying to raise the
        # score until it plateaus or the round budget runs out, then ships this
        # best accepted draft. A COMPLETED run exists iff this is populated.
        self.best_accepted_submission: dict | None = None
        self.best_accepted_gate_report: dict = {}
        self.best_accepted_scores: dict = {}
        self.best_accepted_overall: float | None = None

    # -- per-round updates --------------------------------------------------

    def begin_round(self, submitted: dict) -> None:
        """Count a submit attempt and remember what was submitted."""
        self.rounds_used += 1
        self.submitted = submitted

    def record_gate_result(self, accepted: bool, report: dict) -> None:
        self.accepted = accepted
        self.last_gate_report = report
        self.final_scores = (report.get("panel") or {}).get("rollup", {})

    def track_plateau(self, report: dict) -> None:
        """Update the panel-score plateau counters from this round's rollup.

        ``best_overall`` is the highest overall seen; ``rounds_since_improvement``
        counts consecutive rounds that failed to beat it. The overall is a mean of
        seven integer criteria, so the smallest real gain is ~0.14 and an unchanged
        draft scores bit-identically: a plain ``>`` needs no epsilon guard."""
        panel = report.get("panel") or {}
        overall = panel.get("overall")
        if not isinstance(overall, (int, float)):
            return
        overall = float(overall)
        if self.best_overall is None or overall > self.best_overall:
            self.best_overall = overall
            self.rounds_since_improvement = 0
            self._capture_best(report)
        else:
            self.rounds_since_improvement += 1

    def _capture_best(self, report: dict) -> None:
        """Snapshot the current round as the best-so-far submission.

        Called only when this round set a new ``best_overall``. Each round builds
        fresh ``submitted``/``report``/``final_scores`` dicts, so storing
        references (not copies) is safe -- they are never mutated in place."""
        self.best_submission = self.submitted
        self.best_gate_report = report
        self.best_scores = self.final_scores

    def track_accepted(self, accepted: bool, report: dict) -> None:
        """Snapshot this round if it cleared every gate and beat the best so far.

        Only fully-accepted rounds are eligible to ship, and among them the
        highest panel overall wins -- so a later round that clears the gates but
        scores lower never displaces an earlier, better accepted draft. Must be
        called after ``record_gate_result`` so ``final_scores`` reflects this
        round."""
        if not accepted:
            return
        overall = (report.get("panel") or {}).get("overall")
        if not isinstance(overall, (int, float)):
            return
        overall = float(overall)
        if self.best_accepted_overall is None or overall > self.best_accepted_overall:
            self.best_accepted_overall = overall
            self.best_accepted_submission = self.submitted
            self.best_accepted_gate_report = report
            self.best_accepted_scores = self.final_scores

    @property
    def has_accepted(self) -> bool:
        """At least one round cleared every gate, so the run can ship a draft."""
        return self.best_accepted_submission is not None

    def accepted_outcome(self) -> tuple[dict, dict, dict]:
        """The ``(submission, gate_report, scores)`` a COMPLETED run ships.

        The highest-scoring round that cleared every gate -- not necessarily the
        last, since the loop keeps revising past the bar and a later round can
        regress. Only valid when ``has_accepted`` is true."""
        return (
            self.best_accepted_submission or {},
            self.best_accepted_gate_report,
            self.best_accepted_scores,
        )

    def plateaued(self) -> bool:
        """The panel overall has stopped improving for ``plateau_patience`` rounds.

        Independent of whether the round cleared the bar: once the score stops
        climbing there is nothing to gain from more rounds, whether the draft is
        already acceptable (ship the best) or still short (give up)."""
        return self.rounds_since_improvement >= self.config.plateau_patience

    @property
    def rounds_exhausted(self) -> bool:
        return self.rounds_used >= self.config.max_rounds

    # -- agent termination ----------------------------------------------------

    def record_agent_result(self, result) -> None:
        """Capture how a cleanly-returning core agent stopped."""
        self.agent_stop_reason = result.stop_reason

    def record_agent_error(self, exc: AgentRunError) -> None:
        """Classify a core-agent failure by type into the fields
        ``failure_message`` reads (stop reason, detail)."""
        if isinstance(exc, IterationLimitError):
            self.agent_stop_reason = "iteration_cap"
        elif isinstance(exc, IncompleteTurnError):
            self.agent_stop_reason = "incomplete_turn"
            self.agent_error = exc.stop_reason
        else:
            self.agent_stop_reason = "provider_error"
            self.agent_error = str(exc)

    # -- terminal outcome -----------------------------------------------------

    def persisted_outcome(self) -> tuple[dict, dict, dict]:
        """The ``(submission, gate_report, scores)`` a FAILED run persists.

        The BEST-scoring round, not merely the last -- a plateau can stop the
        loop on a round that regressed below an earlier peak. The gate report
        and scores come from the same round so the persisted draft and its
        evaluation stay consistent. Falls back to the last submission (``{}``
        when the agent never submitted) if no round produced a scored panel to
        rank."""
        if self.best_submission is not None:
            return self.best_submission, self.best_gate_report, self.best_scores
        return self.submitted or {}, self.last_gate_report, self.final_scores

    def failure_message(self) -> str:
        """A specific reason the run failed, distinguishing the paths that used
        to collapse to one opaque string (iteration cap vs. give-up vs. plateau
        vs. round budget vs. the ways the core agent can die mid-run)."""
        if self.gate_crash:
            return f"gate check crashed on round {self.rounds_used}: {self.gate_crash}"
        if self.panel_unavailable:
            detail = f": {self.panel_error}" if self.panel_error else ""
            return (
                "judge panel unavailable (no judge returned a score) on round "
                f"{self.rounds_used}{detail}"
            )
        if self.submitted is None and self.agent_stop_reason in (
            "incomplete_turn",
            "provider_error",
        ):
            # The agent died before ever submitting; name the real cause, not
            # a give-up.
            return self._agent_stop_message()
        if self.submitted is None:
            return "agent did not submit a proposal"
        if self.stopped_on_plateau:
            return (
                f"panel score plateaued at {self.best_overall} for "
                f"{self.rounds_since_improvement} rounds without clearing every "
                f"gate (bar {self.config.panel_threshold}); stopped after "
                f"{self.rounds_used} of {self.config.max_rounds} rounds"
            )
        if self.rounds_used >= self.config.max_rounds:
            return f"gates not cleared within {self.config.max_rounds} rounds"
        if self.agent_stop_reason == "iteration_cap":
            return (
                f"agent hit the {self.config.max_iterations}-iteration cap after "
                f"{self.rounds_used} of {self.config.max_rounds} rounds; raise "
                "RESEARCH_AI_PROPOSAL_MAX_ITERATIONS or reduce per-round tool use"
            )
        if self.agent_stop_reason in ("incomplete_turn", "provider_error"):
            return self._agent_stop_message()
        return (
            f"agent ended without an accepted proposal after {self.rounds_used} rounds"
        )

    def _agent_stop_message(self) -> str:
        """Name how the core agent died mid-run, with the actionable detail."""
        if self.agent_stop_reason == "incomplete_turn":
            return (
                f"model stopped mid-run ({self.agent_error}) after "
                f"{self.rounds_used} rounds"
            )
        return (
            f"agent stopped on a provider error after {self.rounds_used} rounds: "
            f"{self.agent_error}"
        )
