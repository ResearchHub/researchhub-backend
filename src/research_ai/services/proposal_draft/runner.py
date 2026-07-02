"""Driver for the headless proposal-drafting run.

Composes the agent core, the profile builder, the ``ProposalDraft`` job record,
and the proposal tools + judge panel into one bounded run: build the agent, let
it draft/critique/verify/revise in a tool loop, and write the verified proposal
as a ``Note``.

The division of labour is the whole point of the agentic design:

- the **agent** (an LLM in a tool loop) owns judgment -- what to research, how to
  draft, when it thinks the draft is ready;
- the **tools** own ground truth -- the RFP terms, the researcher's real works,
  deterministic citation resolution, the multi-model panel's scores;
- this **driver** owns the gates and the write -- it never trusts the model's
  own "this is done" signal. The terminal ``submit_proposal`` tool hands the
  draft back here; the ``ProposalGateRunner`` re-runs verification and the
  panel and only lets the loop stop when the draft actually clears every gate.
  While rounds remain, a rejected submit feeds its concrete gaps back to the
  model with ``stop=False`` so it revises in place.

Bounded termination: the loop stops when a submit clears the gates, when
``max_rounds`` submit attempts are spent, when the panel score plateaus below
the bar (no improvement for ``plateau_patience`` rounds -- grinding a flat
single-judge score buys nothing), or when the core agent hits its iteration
cap. All non-accepting exits end in ``FAILED`` with the final ``gate_report``
and a specific ``error_message`` naming which bound tripped (iteration cap vs.
give-up vs. plateau vs. round budget vs. a provider failure). A terminal
safety net converts any unexpected exception to the same ``FAILED`` shape --
no run ends with the record still saying ``PROCESSING``.

The pieces live beside this module: ``config`` (the settings-backed knobs),
``gates`` (the deterministic accept/reject checks), and ``note_writer`` (the
headless ``Note`` write). Judge-facing context compaction lives with the other
tool code in ``research_ai.services.proposal_tools.judge_context``.
"""

import logging

from django.conf import settings
from django.utils import timezone

from research_ai.models import ProposalDraft, SearchExpert
from research_ai.prompts.proposal_draft_prompts import (
    build_proposal_system_prompt,
    build_proposal_user_prompt,
)
from research_ai.services.agent import (
    AgentRunError,
    AgentService,
    BedrockProvider,
    IncompleteTurnError,
    IterationLimitError,
    Tool,
    Toolset,
)
from research_ai.services.proposal_draft.config import ProposalDraftConfig
from research_ai.services.proposal_draft.gates import ProposalGateRunner
from research_ai.services.proposal_draft.note_writer import write_proposal_note
from research_ai.services.proposal_judge_panel import ProposalJudgePanel
from research_ai.services.proposal_tools import (
    ProposalContextToolset,
    ProposalFulltextToolset,
    ProposalVerificationToolset,
    ProposalWebSearchToolset,
    build_judge_tool,
)
from research_ai.services.proposal_tools.judge_context import build_judge_context
from research_ai.services.researcher_profile import build_and_store_expert_profile
from research_ai.services.researcher_profile.openalex_tools import (
    SUBMIT_PROFILE,
    OpenAlexToolset,
)
from utils.openalex import OpenAlex

logger = logging.getLogger(__name__)

_SUBMIT_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "hypothesis": {"type": "string"},
                "approach": {"type": "string"},
                "why_this_team": {"type": "string"},
                "scope_timeline": {"type": "string"},
            },
            "required": [
                "title",
                "hypothesis",
                "approach",
                "why_this_team",
                "scope_timeline",
            ],
        },
        "prosemirror": {
            "type": "object",
            "description": 'ProseMirror doc: {"type": "doc", "content": [...]}.',
        },
        "plain_text": {
            "type": "string",
            "description": "The full proposal as readable plain text.",
        },
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim_id": {"type": "string"},
                    "doi": {"type": "string"},
                    "title": {"type": "string"},
                    "authors": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["claim_id"],
            },
        },
    },
    "required": ["sections", "prosemirror", "plain_text"],
}


class _ProposalDraftRunner:
    """One bounded proposal-drafting run against a single ``ProposalDraft``."""

    def __init__(
        self,
        search_expert: SearchExpert,
        draft: ProposalDraft,
        *,
        progress_callback=None,
        provider=None,
        panel: ProposalJudgePanel | None = None,
        oa_client: OpenAlex | None = None,
        web_search_client=None,
        config: ProposalDraftConfig | None = None,
    ):
        self.search_expert = search_expert
        self.expert = search_expert.expert
        self.draft = draft
        self.progress_callback = progress_callback
        self.provider = provider
        self.oa_client = oa_client or OpenAlex()
        self.web_search_client = web_search_client
        self.panel = panel or ProposalJudgePanel()
        self.config = config or ProposalDraftConfig.from_settings()

        # Shared across the run: provenance the citation gate grounds against.
        self.provenance: set[str] = set()
        self.context_toolset = ProposalContextToolset(
            search_expert, provenance=self.provenance
        )
        self.verification_toolset = ProposalVerificationToolset(
            oa_client=self.oa_client
        )
        self.fulltext_toolset = ProposalFulltextToolset(search_expert)
        self.openalex_toolset = OpenAlexToolset(client=self.oa_client)
        # Its own provenance -- deliberately NOT self.provenance -- so web results
        # ground the prose but can never satisfy the citation gate.
        self.web_search_toolset = ProposalWebSearchToolset(client=web_search_client)
        self._submit_tool: Tool | None = None

        self.gates = ProposalGateRunner(
            config=self.config,
            panel=self.panel,
            verification_toolset=self.verification_toolset,
            judge_context=self._judge_context,
            grounded_urls=self._grounded_urls,
            on_step=self._set_step,
        )

        # Loop state captured by the submit handler / gate runner.
        self.rounds_used = 0
        self.accepted = False
        self.submitted: dict | None = None
        self.last_gate_report: dict = {}
        self.final_scores: dict = {}
        self.rfp_context: dict = {}

        # How the core agent terminated (filled after ``agent.run`` returns/raises)
        # and the panel-score plateau tracking -- both feed the specific failure
        # message a FAILED run records. ``agent_error`` carries the detail
        # (provider error text, truncation stop reason) for that message.
        self.agent_stop_reason: str | None = None
        self.agent_iterations: int | None = None
        self.agent_error: str | None = None

        # Infrastructure failures the submit handler contains: a crashed gate
        # check or an empty judge panel ends the run with its real cause
        # instead of letting the model revise against a broken referee.
        self.gate_crash: str | None = None
        self.panel_unavailable = False
        self.best_overall: float | None = None
        self.rounds_since_improvement = 0
        self.stopped_on_plateau = False

        # Snapshot of the highest-scoring round so a FAILED run persists the best
        # draft the agent reached, not merely the last -- a plateau can stop the
        # loop on a round that regressed below an earlier peak.
        self.best_submission: dict | None = None
        self.best_gate_report: dict = {}
        self.best_scores: dict = {}
        self.best_round: int | None = None

    # -- public entry -----------------------------------------------------

    def run(self) -> dict:
        self.draft.status = ProposalDraft.Status.PROCESSING
        self.draft.run_config = {
            "generator_model_id": getattr(self.provider, "model_id", None)
            or getattr(settings, "RESEARCH_AI_GENERATOR_MODEL_ID", None),
            "judge_roster": list(self.panel.model_ids),
            "max_rounds": self.config.max_rounds,
            "panel_threshold": self.config.panel_threshold,
            "max_iterations": self.config.max_iterations,
        }
        self.draft.save(update_fields=["status", "run_config", "updated_date"])
        try:
            return self._run()
        except Exception as exc:  # noqa: BLE001 - no run may end still PROCESSING
            # The terminal safety net: whatever escapes the run body (a note
            # write after an accepted submit, a DB error, a bug) still lands
            # the record in FAILED with a real message, never a stuck
            # PROCESSING with no explanation.
            logger.exception("proposal draft run crashed")
            return self._fail(f"unexpected error: {exc}")

    def _run(self) -> dict:
        # Fail before the (expensive) profile build when there is no RFP to
        # draft against -- the run could never succeed.
        self.rfp_context = self.context_toolset.get_rfp_context()
        if "error" in self.rfp_context:
            return self._fail(f"cannot draft: {self.rfp_context['error']}")

        self._ensure_profile()

        system_prompt = build_proposal_system_prompt(
            panel_threshold=self.config.panel_threshold
        )
        user_prompt = build_proposal_user_prompt(self.expert, self.rfp_context)
        agent = self._build_agent(system_prompt)

        self._set_step(ProposalDraft.Step.DRAFTING)
        try:
            result = agent.run(user_prompt)
            self.agent_stop_reason = result.stop_reason
            self.agent_iterations = result.iterations
        except AgentRunError as exc:
            # Core iteration cap hit, a truncated/filtered turn, or a provider
            # error after a partial run.
            logger.warning("proposal draft agent stopped early: %s", exc)
            self._record_agent_error(exc)

        if self.accepted and self.submitted is not None:
            return self._complete()
        return self._fail()

    def _record_agent_error(self, exc: AgentRunError) -> None:
        """Classify a core-agent failure by type into the loop-state fields
        ``_failure_message`` reads (stop reason, iterations, detail)."""
        self.agent_iterations = exc.iterations
        if isinstance(exc, IterationLimitError):
            self.agent_stop_reason = "iteration_cap"
        elif isinstance(exc, IncompleteTurnError):
            self.agent_stop_reason = "incomplete_turn"
            self.agent_error = exc.stop_reason
        else:
            self.agent_stop_reason = "provider_error"
            self.agent_error = str(exc)

    # -- setup ------------------------------------------------------------

    def _ensure_profile(self) -> None:
        """Build + persist the researcher profile when it is missing/stale."""
        if not _needs_profile(self.expert.profile):
            return
        self._set_step(ProposalDraft.Step.BUILDING_PROFILE)
        try:
            build_and_store_expert_profile(
                self.expert, provider=self.provider, oa_client=self.oa_client
            )
        except Exception:  # noqa: BLE001 - profile build is best-effort
            logger.exception("proposal draft: profile build failed")

    def _build_agent(self, system_prompt: str):
        provider = self.provider or BedrockProvider()
        toolset = self._compose_toolset()
        return AgentService(
            provider=provider, max_iterations=self.config.max_iterations
        ).create_agent(
            toolset,
            system_prompt=system_prompt,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
        )

    def _compose_toolset(self) -> Toolset:
        """OpenAlex + context + verification + judge + terminal submit, one set."""
        toolset = Toolset()
        # OpenAlex tools, minus that toolset's own terminal submit_profile -- the
        # proposal agent has its own terminal tool.
        for tool in self.openalex_toolset.build_tools():
            if tool.name == SUBMIT_PROFILE:
                continue
            toolset.add(tool)
        for tool in self.context_toolset.build_tools():
            toolset.add(tool)
        for tool in self.fulltext_toolset.build_tools():
            toolset.add(tool)
        for tool in self.web_search_toolset.build_tools():
            toolset.add(tool)
        for tool in self.verification_toolset.build_tools():
            toolset.add(tool)
        toolset.add(
            build_judge_tool(
                self.panel,
                context_provider=self._judge_tool_context,
            )
        )
        toolset.add(self._build_submit_tool())
        return toolset

    def _build_submit_tool(self) -> Tool:
        """The terminal ``submit_proposal`` tool, gated by the driver.

        Terminality is decided per call: the gates run inside the handler, and
        the tool only ends the loop when the draft is accepted or the round
        budget is spent. While rounds remain, a rejected submit returns its gaps
        with the tool non-terminal so the agent revises and submits again.
        """
        self._submit_tool = Tool(
            name="submit_proposal",
            description=(
                "Submit the finished proposal for the deterministic gate. Provide "
                "sections (title, hypothesis, approach, why_this_team, "
                "scope_timeline), a ProseMirror `prosemirror` doc, `plain_text`, "
                "and `citations` (each from a tool result). If the gate rejects "
                "the draft it returns concrete gaps -- revise and submit again."
            ),
            input_schema=_SUBMIT_INPUT_SCHEMA,
            handler=self._handle_submit,
            is_terminal=False,
        )
        return self._submit_tool

    # -- the gate-before-stop handler ------------------------------------

    def _handle_submit(self, args: dict) -> dict:
        submitted = args or {}
        self.rounds_used += 1
        self.submitted = submitted
        try:
            accepted, report = self.gates.run(submitted, round_number=self.rounds_used)
        except Exception as exc:  # noqa: BLE001 - a broken gate must end the run
            # Contained here because ``Toolset.dispatch`` would otherwise hand
            # the crash back to the model as a retryable tool error, and it
            # would burn the remaining rounds revising against a broken
            # referee -- with the run then mis-blamed on the iteration cap.
            logger.exception("proposal draft gate check crashed")
            self.gate_crash = str(exc) or type(exc).__name__
            self._persist_round()
            self._submit_tool.is_terminal = True
            return {"accepted": False, "stopped": "gate_error"}
        self.accepted = accepted
        self.last_gate_report = report
        self.final_scores = (report.get("panel") or {}).get("rollup", {})
        if (report.get("panel") or {}).get("unavailable"):
            # An empty panel is an infrastructure failure, not a verdict --
            # same containment as a crashed gate.
            self.panel_unavailable = True
            self._persist_round()
            self._submit_tool.is_terminal = True
            return {
                "accepted": False,
                "stopped": "panel_unavailable",
                "gate_report": report,
            }
        self._track_plateau(report)

        exhausted = self.rounds_used >= self.config.max_rounds
        # Cut a run short only when the panel is the blocker and its score has
        # stopped improving; a passing panel held up by a mechanical gate is
        # still worth revising, and the round budget takes precedence anyway.
        plateaued = not accepted and not exhausted and self._panel_plateaued(report)
        self.stopped_on_plateau = plateaued
        self._persist_round()

        # End the loop on a clean submit, when no rounds remain to revise, or
        # when the panel score has plateaued below the bar.
        self._submit_tool.is_terminal = accepted or exhausted or plateaued

        if accepted:
            self._set_step(ProposalDraft.Step.WRITING_NOTE)
            return {"accepted": True, "gate_report": report}
        if exhausted:
            return {
                "accepted": False,
                "exhausted": True,
                "gaps": report["gaps"],
                "gate_report": report,
            }
        if plateaued:
            return {
                "accepted": False,
                "stopped": "plateau",
                "gaps": report["gaps"],
                "gate_report": report,
            }
        self._set_step(ProposalDraft.Step.REVISING)
        return self._revise_feedback(report)

    def _track_plateau(self, report: dict) -> None:
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
        self.best_round = self.rounds_used

    def _panel_plateaued(self, report: dict) -> bool:
        """The panel is the blocker and its overall has stopped improving."""
        if (report.get("panel") or {}).get("ok"):
            return False
        return self.rounds_since_improvement >= self.config.plateau_patience

    def _revise_feedback(self, report: dict) -> dict:
        """Rejection payload for the revising agent: the gaps plus the panel's
        per-criterion scores, so it can target the weak criteria instead of
        rewriting ones already scoring well (overall is also in the gap text)."""
        panel = report.get("panel") or {}
        return {
            "accepted": False,
            "gaps": report["gaps"],
            "scores": panel.get("scores"),
            "overall": panel.get("overall"),
            "threshold": panel.get("threshold"),
        }

    def _persist_round(self) -> None:
        """Write this round's outcome to the record as soon as the gates run.

        Terminal ``_complete``/``_fail`` still write the authoritative final
        state, but persisting per round means an in-flight run -- or one that
        hangs or dies mid-loop before reaching a terminal path -- is inspectable
        with the latest submission, scores, and gate report rather than the
        zeroed defaults.
        """
        self.draft.rounds_used = self.rounds_used
        self.draft.final_scores = self.final_scores
        self.draft.gate_report = self.last_gate_report
        self.draft.last_submission = self.submitted or {}
        self.draft.save(
            update_fields=[
                "rounds_used",
                "final_scores",
                "gate_report",
                "last_submission",
                "updated_date",
            ]
        )

    # -- judge context ------------------------------------------------------

    def _judge_tool_context(self, args: dict) -> dict:
        """Server-side judge context for the agent-facing ``judge_proposal`` tool."""
        return self._judge_context({"citations": args.get("citations") or []})

    def _judge_context(self, submitted: dict | None = None) -> dict:
        """Evidence judges need for RFP fit, budget fit, credibility, and novelty."""
        submitted = submitted or {}
        return build_judge_context(
            rfp_context=self.rfp_context,
            profile=self.expert.profile,
            citations=submitted.get("citations"),
            grounded_urls=self._grounded_urls(),
            max_rfp_chars=self.config.max_judge_rfp_chars,
            max_works=self.config.max_judge_works,
            max_abstract_chars=self.config.max_judge_abstract_chars,
        )

    def _grounded_urls(self) -> set[str]:
        """Every URL a citation may ground against: profile + OpenAlex results."""
        urls = set(self.provenance)
        for url, record in self.openalex_toolset.returned_works.items():
            urls.add(url)
            if isinstance(record, dict) and record.get("pdf_url"):
                urls.add(record["pdf_url"])
        return urls

    # -- terminal outcomes ------------------------------------------------

    def _complete(self) -> dict:
        note = write_proposal_note(self.submitted)
        self.draft.note = note
        self.draft.final_scores = self.final_scores
        self.draft.gate_report = self.last_gate_report
        self.draft.rounds_used = self.rounds_used
        self.draft.status = ProposalDraft.Status.COMPLETED
        self.draft.step = ProposalDraft.Step.DONE
        self.draft.completed_at = timezone.now()
        self.draft.save()
        self._emit_progress(ProposalDraft.Step.DONE)
        return {
            "status": ProposalDraft.Status.COMPLETED,
            "proposal_draft_id": self.draft.id,
            "note_id": note.id,
            "rounds_used": self.rounds_used,
            "final_scores": self.final_scores,
            "gate_report": self.last_gate_report,
        }

    def _fail(self, message: str | None = None) -> dict:
        message = message or self._failure_message()
        self.draft.rounds_used = self.rounds_used
        # Persist the rejected draft so a failed run is still inspectable: a
        # FAILED run never writes a Note, so this is the only place its content
        # survives. Keep the BEST-scoring round, not merely the last -- a plateau
        # can stop the loop on a round that regressed below an earlier peak. The
        # gate report and scores are kept from the same round so the persisted
        # draft and its evaluation stay consistent. Fall back to the last
        # submission (``{}`` when the agent never submitted) if no round produced
        # a scored panel to rank.
        if self.best_submission is not None:
            self.draft.last_submission = self.best_submission
            self.draft.gate_report = self.best_gate_report
            self.draft.final_scores = self.best_scores
        else:
            self.draft.last_submission = self.submitted or {}
            self.draft.gate_report = self.last_gate_report
            self.draft.final_scores = self.final_scores
        self.draft.status = ProposalDraft.Status.FAILED
        self.draft.error_message = message
        self.draft.save()
        return {
            "status": ProposalDraft.Status.FAILED,
            "proposal_draft_id": self.draft.id,
            "rounds_used": self.rounds_used,
            "gate_report": self.draft.gate_report,
            "last_submission": self.draft.last_submission,
            "error_message": message,
        }

    def _failure_message(self) -> str:
        """A specific reason the run failed, distinguishing the paths that used
        to collapse to one opaque string (iteration cap vs. give-up vs. plateau
        vs. round budget vs. the ways the core agent can die mid-run)."""
        if self.gate_crash:
            return f"gate check crashed on round {self.rounds_used}: {self.gate_crash}"
        if self.panel_unavailable:
            return (
                "judge panel unavailable (no judge returned a score) on round "
                f"{self.rounds_used}"
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
                f"{self.rounds_since_improvement} rounds below the "
                f"{self.config.panel_threshold} bar; stopped after "
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

    # -- progress ---------------------------------------------------------

    def _set_step(self, step: str) -> None:
        if self.draft.step != step:
            self.draft.step = step
            self.draft.save(update_fields=["step", "updated_date"])
        self._emit_progress(step)

    def _emit_progress(self, step: str) -> None:
        if self.progress_callback is None:
            return
        try:
            self.progress_callback(
                {
                    "step": step,
                    "status": self.draft.status,
                    "rounds_used": self.rounds_used,
                }
            )
        except Exception:  # noqa: BLE001 - progress must not break the run
            logger.debug("proposal draft progress callback failed", exc_info=True)


def _needs_profile(profile) -> bool:
    """A profile needs (re)building when it is empty or has no resolution."""
    if not isinstance(profile, dict) or not profile:
        return True
    return not isinstance(profile.get("resolution"), dict)


def run_proposal_draft(
    search_expert_id,
    *,
    progress_callback=None,
    provider=None,
    panel: ProposalJudgePanel | None = None,
    oa_client: OpenAlex | None = None,
    web_search_client=None,
) -> dict:
    """Run a headless proposal-drafting job for one ``SearchExpert``.

    Creates a ``ProposalDraft``, builds the agent, runs the bounded
    draft -> critique -> verify -> revise loop with a deterministic gate before
    stop, and writes the verified proposal as a ``Note``. Returns a result dict
    carrying the final status, the gate report, and (on success) the note id.

    ``provider`` / ``panel`` / ``oa_client`` / ``web_search_client`` are
    injectable for tests; in production they default to the real Bedrock
    provider, judge panel, OpenAlex client, and Brave web-search client.
    """
    search_expert = SearchExpert.objects.select_related(
        "expert", "expert_search", "expert_search__unified_document"
    ).get(id=search_expert_id)
    draft = ProposalDraft.objects.create(
        search_expert=search_expert,
        status=ProposalDraft.Status.PENDING,
        step=ProposalDraft.Step.QUEUED,
    )
    runner = _ProposalDraftRunner(
        search_expert,
        draft,
        progress_callback=progress_callback,
        provider=provider,
        panel=panel,
        oa_client=oa_client,
        web_search_client=web_search_client,
    )
    return runner.run()
