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
``gates`` (the deterministic accept/reject checks), ``run_state`` (the loop
bookkeeping and failure-reason taxonomy), ``draft_recorder`` (every
``ProposalDraft`` write and progress emission), ``toolset`` (the submit tool
and toolset composition), and ``note_writer`` (the headless ``Note`` write).
Judge-facing context compaction lives with the other tool code in
``research_ai.services.proposal_tools.judge_context``.
"""

import logging

from django.conf import settings

from research_ai.models import ProposalDraft, SearchExpert
from research_ai.prompts.proposal_draft_prompts import (
    build_proposal_system_prompt,
    build_proposal_user_prompt,
)
from research_ai.services.agent import (
    AgentRunError,
    AgentService,
    BedrockProvider,
    Tool,
    Toolset,
)
from research_ai.services.proposal_draft.config import ProposalDraftConfig
from research_ai.services.proposal_draft.draft_recorder import DraftRecorder
from research_ai.services.proposal_draft.gates import ProposalGateRunner
from research_ai.services.proposal_draft.note_writer import write_proposal_note
from research_ai.services.proposal_draft.run_state import ProposalRunState
from research_ai.services.proposal_draft.toolset import (
    build_submit_tool,
    compose_proposal_toolset,
)
from research_ai.services.proposal_judge_panel import ProposalJudgePanel
from research_ai.services.proposal_tools import (
    ProposalContextToolset,
    ProposalFulltextToolset,
    ProposalVerificationToolset,
    ProposalWebSearchToolset,
)
from research_ai.services.proposal_tools.judge_context import build_judge_context
from research_ai.services.researcher_profile import build_and_store_expert_profile
from research_ai.services.researcher_profile.openalex_tools import OpenAlexToolset
from utils.openalex import OpenAlex

logger = logging.getLogger(__name__)


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
        self.provider = provider
        self.oa_client = oa_client or OpenAlex()
        self.web_search_client = web_search_client
        self.panel = panel or ProposalJudgePanel()
        self.config = config or ProposalDraftConfig.from_settings()

        self.state = ProposalRunState(self.config)
        self.recorder = DraftRecorder(
            draft, self.state, progress_callback=progress_callback
        )

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
            on_step=self.recorder.set_step,
        )

        self.rfp_context: dict = {}

    # -- public entry -----------------------------------------------------

    def run(self) -> dict:
        self.recorder.mark_processing(
            {
                "generator_model_id": getattr(self.provider, "model_id", None)
                or getattr(settings, "RESEARCH_AI_GENERATOR_MODEL_ID", None),
                "judge_roster": list(self.panel.model_ids),
                "max_rounds": self.config.max_rounds,
                "panel_threshold": self.config.panel_threshold,
                "max_iterations": self.config.max_iterations,
            }
        )
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

        self.recorder.set_step(ProposalDraft.Step.DRAFTING)
        try:
            result = agent.run(user_prompt)
            self.state.record_agent_result(result)
        except AgentRunError as exc:
            # Core iteration cap hit, a truncated/filtered turn, or a provider
            # error after a partial run.
            logger.warning("proposal draft agent stopped early: %s", exc)
            self.state.record_agent_error(exc)

        if self.state.accepted and self.state.submitted is not None:
            return self._complete()
        return self._fail()

    # -- setup ------------------------------------------------------------

    def _ensure_profile(self) -> None:
        """Build + persist the researcher profile when it is missing/stale."""
        if not _needs_profile(self.expert.profile):
            return
        self.recorder.set_step(ProposalDraft.Step.BUILDING_PROFILE)
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
        self._submit_tool = build_submit_tool(self._handle_submit)
        return compose_proposal_toolset(
            openalex_toolset=self.openalex_toolset,
            context_toolset=self.context_toolset,
            fulltext_toolset=self.fulltext_toolset,
            web_search_toolset=self.web_search_toolset,
            verification_toolset=self.verification_toolset,
            panel=self.panel,
            judge_context_provider=self._judge_tool_context,
            submit_tool=self._submit_tool,
        )

    # -- the gate-before-stop handler ------------------------------------

    def _handle_submit(self, args: dict) -> dict:
        state = self.state
        state.begin_round(args or {})
        try:
            accepted, report = self.gates.run(
                state.submitted, round_number=state.rounds_used
            )
        except Exception as exc:  # noqa: BLE001 - a broken gate must end the run
            # Contained here because ``Toolset.dispatch`` would otherwise hand
            # the crash back to the model as a retryable tool error, and it
            # would burn the remaining rounds revising against a broken
            # referee -- with the run then mis-blamed on the iteration cap.
            logger.exception("proposal draft gate check crashed")
            state.gate_crash = str(exc) or type(exc).__name__
            self.recorder.persist_round()
            self._submit_tool.is_terminal = True
            return {"accepted": False, "stopped": "gate_error"}
        state.record_gate_result(accepted, report)
        if (report.get("panel") or {}).get("unavailable"):
            # An empty panel is an infrastructure failure, not a verdict --
            # same containment as a crashed gate.
            state.panel_unavailable = True
            self.recorder.persist_round()
            self._submit_tool.is_terminal = True
            return {
                "accepted": False,
                "stopped": "panel_unavailable",
                "gate_report": report,
            }
        state.track_plateau(report)

        exhausted = state.rounds_exhausted
        # Cut a run short only when the panel is the blocker and its score has
        # stopped improving; a passing panel held up by a mechanical gate is
        # still worth revising, and the round budget takes precedence anyway.
        plateaued = not accepted and not exhausted and state.panel_plateaued(report)
        state.stopped_on_plateau = plateaued
        self.recorder.persist_round()

        # End the loop on a clean submit, when no rounds remain to revise, or
        # when the panel score has plateaued below the bar.
        self._submit_tool.is_terminal = accepted or exhausted or plateaued

        if accepted:
            self.recorder.set_step(ProposalDraft.Step.WRITING_NOTE)
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
        self.recorder.set_step(ProposalDraft.Step.REVISING)
        return self._revise_feedback(report)

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
        note = write_proposal_note(self.state.submitted)
        return self.recorder.complete(note)

    def _fail(self, message: str | None = None) -> dict:
        return self.recorder.fail(message or self.state.failure_message())


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
