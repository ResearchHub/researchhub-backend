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
  draft back here; ``_run_gates`` re-runs verification and the panel and only
  lets the loop stop when the draft actually clears every gate. While rounds
  remain, a rejected submit feeds its concrete gaps back to the model with
  ``stop=False`` so it revises in place.

Bounded termination: the loop stops when a submit clears the gates, when
``MAX_ROUNDS`` submit attempts are spent, or when the core agent hits its
iteration cap -- the last two end in ``FAILED`` with the final ``gate_report``
recorded for diagnosis.
"""

import json
import logging
import re

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from note.models import Note, NoteContent
from research_ai.models import ProposalDraft, SearchExpert
from research_ai.prompts.proposal_draft_prompts import (
    build_proposal_system_prompt,
    build_proposal_user_prompt,
)
from research_ai.services.agent import AgentService, BedrockProvider, Tool, Toolset
from research_ai.services.proposal_judge_panel import ProposalJudgePanel
from research_ai.services.proposal_tools import (
    ProposalContextToolset,
    ProposalFulltextToolset,
    ProposalVerificationToolset,
    build_judge_tool,
)
from research_ai.services.proposal_tools.doi import strip_doi_prefix
from research_ai.services.researcher_profile import build_and_store_expert_profile
from research_ai.services.researcher_profile.openalex_tools import (
    SUBMIT_PROFILE,
    OpenAlexToolset,
)
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import NOTE
from utils.openalex import OpenAlex

logger = logging.getLogger(__name__)

# Bounded-loop defaults (settings-overridable). MAX_ROUNDS bounds submit
# attempts (one round = one submit + gate pass); the agent's iteration cap is a
# looser ceiling on total tool turns so several tool calls can precede each
# submit.
_DEFAULT_MAX_ROUNDS = 8
_DEFAULT_PANEL_THRESHOLD = 4.5
# Sized so MAX_ROUNDS (not this cap) is the real limiter: front-loaded research
# turns plus ~8 revise/judge/verify rounds need well over the old 40, which
# strangled runs mid-revision (e.g. quitting at round 3 of 8).
_DEFAULT_MAX_ITERATIONS = 100
_DEFAULT_MAX_TOKENS = 16384
_DEFAULT_TEMPERATURE = 1.0

# Length bounds on the readable proposal (words). Wide on purpose: the gate
# catches an empty/stub draft or a runaway, not stylistic length.
_DEFAULT_MIN_WORDS = 250
_DEFAULT_MAX_WORDS = 4000
_DEFAULT_MAX_JUDGE_RFP_CHARS = 6000
_DEFAULT_MAX_JUDGE_WORKS = 8
_DEFAULT_MAX_JUDGE_ABSTRACT_CHARS = 1200

# Sections the proposal must carry (keys on the submitted ``sections`` object).
_REQUIRED_SECTIONS = (
    ("title", "title"),
    ("hypothesis", "hypothesis / aim"),
    ("approach", "approach / methods"),
    ("why_this_team", "why this team"),
    ("scope_timeline", "scope & timeline"),
)

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


def _provenance_keys(urls) -> set[str]:
    """Comparable keys for a set of provenance URLs (raw + DOI-normalized)."""
    keys: set[str] = set()
    for url in urls:
        raw = str(url or "").strip().lower()
        if not raw:
            continue
        keys.add(raw)
        keys.add(strip_doi_prefix(raw))
    return {k for k in keys if k}


def _citation_keys(citation: dict) -> set[str]:
    """Comparable keys a citation could ground against."""
    keys: set[str] = set()
    for value in (citation.get("doi"), citation.get("source_url")):
        raw = str(value or "").strip().lower()
        if raw:
            keys.add(raw)
            keys.add(strip_doi_prefix(raw))
    return {k for k in keys if k}


def _trim_context_text(value: object, max_chars: int) -> str:
    """Trim long context strings without cutting mid-word when practical."""
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    trimmed = text[:max_chars].rsplit(" ", 1)[0].rstrip()
    return (trimmed or text[:max_chars]).rstrip() + "..."


def _compact_rfp_context(rfp_ctx: dict, *, max_chars: int) -> dict:
    """Small judge-facing RFP context: structured terms plus trimmed call text."""
    rfp_ctx = rfp_ctx if isinstance(rfp_ctx, dict) else {}
    out = {
        "organization": rfp_ctx.get("organization"),
        "short_title": rfp_ctx.get("short_title"),
        "amount": rfp_ctx.get("amount"),
        "currency": rfp_ctx.get("currency"),
        "end_date": rfp_ctx.get("end_date"),
    }
    if rfp_ctx.get("error"):
        out["error"] = rfp_ctx["error"]
    rfp_text = _trim_context_text(rfp_ctx.get("rfp_text"), max_chars)
    if rfp_text:
        out["rfp_text"] = rfp_text
    return {k: v for k, v in out.items() if v not in (None, "")}


def _compact_profile_context(
    profile: dict,
    *,
    max_works: int,
    max_abstract_chars: int,
) -> dict:
    """Small judge-facing researcher profile for credibility/novelty scoring."""
    profile = profile if isinstance(profile, dict) else {}
    raw_resolution = profile.get("resolution")
    resolution = raw_resolution if isinstance(raw_resolution, dict) else {}
    works = []
    for work in profile.get("works") or []:
        if not isinstance(work, dict):
            continue
        compact = {
            "title": work.get("title"),
            "publication_year": work.get("publication_year"),
            "source_url": work.get("source_url"),
            "author_position": work.get("author_position"),
            "abstract": _trim_context_text(
                work.get("abstract"),
                max_abstract_chars,
            ),
        }
        works.append({k: v for k, v in compact.items() if v not in (None, "")})
        if len(works) >= max_works:
            break
    return {
        "resolution": {
            k: v
            for k, v in resolution.items()
            if k
            in (
                "openalex_author_id",
                "display_name",
                "orcid",
                "confidence",
                "reasoning",
            )
            and v not in (None, "")
        },
        "works": works,
        "errors": profile.get("errors") or [],
    }


def _compact_citations(citations: object) -> list[dict]:
    """Judge-facing structured citations from a submit/tool-call payload."""
    out = []
    for citation in citations or []:
        if not isinstance(citation, dict):
            continue
        compact = {
            "claim_id": citation.get("claim_id"),
            "doi": citation.get("doi"),
            "source_url": citation.get("source_url"),
            "title": citation.get("title"),
            "authors": citation.get("authors") or [],
        }
        out.append({k: v for k, v in compact.items() if v not in (None, "", [])})
    return out


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
    ):
        self.search_expert = search_expert
        self.expert = search_expert.expert
        self.draft = draft
        self.progress_callback = progress_callback
        self.provider = provider
        self.oa_client = oa_client or OpenAlex()
        self.panel = panel or ProposalJudgePanel()

        self.max_rounds = getattr(
            settings, "RESEARCH_AI_PROPOSAL_MAX_ROUNDS", _DEFAULT_MAX_ROUNDS
        )
        self.panel_threshold = getattr(
            settings, "RESEARCH_AI_PROPOSAL_PANEL_THRESHOLD", _DEFAULT_PANEL_THRESHOLD
        )
        self.max_iterations = getattr(
            settings, "RESEARCH_AI_PROPOSAL_MAX_ITERATIONS", _DEFAULT_MAX_ITERATIONS
        )
        self.max_tokens = getattr(
            settings, "RESEARCH_AI_PROPOSAL_MAX_TOKENS", _DEFAULT_MAX_TOKENS
        )
        self.temperature = getattr(
            settings, "RESEARCH_AI_PROPOSAL_TEMPERATURE", _DEFAULT_TEMPERATURE
        )
        self.min_words = getattr(
            settings, "RESEARCH_AI_PROPOSAL_MIN_WORDS", _DEFAULT_MIN_WORDS
        )
        self.max_words = getattr(
            settings, "RESEARCH_AI_PROPOSAL_MAX_WORDS", _DEFAULT_MAX_WORDS
        )
        self.max_judge_rfp_chars = getattr(
            settings,
            "RESEARCH_AI_PROPOSAL_JUDGE_RFP_CHARS",
            _DEFAULT_MAX_JUDGE_RFP_CHARS,
        )
        self.max_judge_works = getattr(
            settings,
            "RESEARCH_AI_PROPOSAL_JUDGE_WORKS",
            _DEFAULT_MAX_JUDGE_WORKS,
        )
        self.max_judge_abstract_chars = getattr(
            settings,
            "RESEARCH_AI_PROPOSAL_JUDGE_ABSTRACT_CHARS",
            _DEFAULT_MAX_JUDGE_ABSTRACT_CHARS,
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
        self._submit_tool: Tool | None = None

        # Loop state captured by the submit handler / gate runner.
        self.rounds_used = 0
        self.accepted = False
        self.submitted: dict | None = None
        self.last_gate_report: dict = {}
        self.final_scores: dict = {}
        self.rfp_context: dict = {}

    # -- public entry -----------------------------------------------------

    def run(self) -> dict:
        self.draft.status = ProposalDraft.Status.PROCESSING
        self.draft.run_config = {
            "generator_model_id": getattr(self.provider, "model_id", None)
            or getattr(settings, "RESEARCH_AI_GENERATOR_MODEL_ID", None),
            "judge_roster": list(self.panel.model_ids),
            "max_rounds": self.max_rounds,
            "panel_threshold": self.panel_threshold,
            "max_iterations": self.max_iterations,
        }
        self.draft.save(update_fields=["status", "run_config", "updated_date"])

        self._ensure_profile()
        self.rfp_context = self.context_toolset.get_rfp_context()

        system_prompt = build_proposal_system_prompt(
            panel_threshold=self.panel_threshold
        )
        user_prompt = build_proposal_user_prompt(self.expert, self.rfp_context)
        agent = self._build_agent(system_prompt)

        self._set_step(ProposalDraft.Step.DRAFTING)
        try:
            agent.run(user_prompt)
        except RuntimeError as exc:
            # Core iteration cap hit, or a provider error after a partial run.
            logger.warning("proposal draft agent stopped early: %s", exc)

        if self.accepted and self.submitted is not None:
            return self._complete()
        return self._fail()

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
            provider=provider, max_iterations=self.max_iterations
        ).create_agent(
            toolset,
            system_prompt=system_prompt,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
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
        accepted, report = self._run_gates(submitted)
        self.accepted = accepted
        self.submitted = submitted
        self.last_gate_report = report

        exhausted = self.rounds_used >= self.max_rounds
        # End the loop on a clean submit, or when no rounds remain to revise.
        self._submit_tool.is_terminal = accepted or exhausted

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
        self._set_step(ProposalDraft.Step.REVISING)
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

    def _run_gates(self, submitted: dict) -> tuple[bool, dict]:
        """Run every deterministic gate; return ``(accepted, report)``."""
        self._set_step(ProposalDraft.Step.VERIFYING)
        sections = submitted.get("sections")
        sections = sections if isinstance(sections, dict) else {}
        gaps: list[str] = []

        section_check = self._gate_sections(sections, submitted)
        length_check = self._gate_length(submitted)
        citation_check = self._gate_citations(submitted)
        scope_check = self._gate_scope(sections)

        self._set_step(ProposalDraft.Step.JUDGING)
        panel_check = self._gate_panel(submitted)
        self.final_scores = panel_check.get("rollup", {})

        for check in (
            section_check,
            length_check,
            citation_check,
            scope_check,
            panel_check,
        ):
            if not check["ok"]:
                gaps.extend(check.get("gaps", []))

        accepted = not gaps
        report = {
            "accepted": accepted,
            "round": self.rounds_used,
            "rounds_used": self.rounds_used,
            "sections": section_check,
            "length": length_check,
            "citations": citation_check,
            "scope": scope_check,
            "panel": panel_check,
            "gaps": gaps,
        }
        return accepted, report

    # -- individual gates -------------------------------------------------

    def _gate_sections(self, sections: dict, submitted: dict) -> dict:
        missing = [
            label
            for key, label in _REQUIRED_SECTIONS
            if not str(sections.get(key) or "").strip()
        ]
        prosemirror_ok = _prosemirror_ok(submitted.get("prosemirror"))
        gaps = [f"Add a non-empty '{label}' section." for label in missing]
        if not prosemirror_ok:
            gaps.append(
                'Provide a valid ProseMirror document ({"type": "doc", '
                '"content": [...]}) with a heading per required section.'
            )
        return {
            "ok": not missing and prosemirror_ok,
            "missing": missing,
            "prosemirror_ok": prosemirror_ok,
            "gaps": gaps,
        }

    def _gate_length(self, submitted: dict) -> dict:
        words = len(str(submitted.get("plain_text") or "").split())
        ok = self.min_words <= words <= self.max_words
        gaps = []
        if words < self.min_words:
            gaps.append(
                f"The proposal is too short ({words} words); expand it past "
                f"{self.min_words} words of real content."
            )
        elif words > self.max_words:
            gaps.append(
                f"The proposal is too long ({words} words); tighten it under "
                f"{self.max_words} words."
            )
        return {
            "ok": ok,
            "words": words,
            "min": self.min_words,
            "max": self.max_words,
            "gaps": gaps,
        }

    def _gate_citations(self, submitted: dict) -> dict:
        citations = [
            c for c in (submitted.get("citations") or []) if isinstance(c, dict)
        ]
        provenance_keys = _provenance_keys(self._grounded_urls())

        ungrounded = [
            str(c.get("claim_id") or "?")
            for c in citations
            if not (_citation_keys(c) & provenance_keys)
        ]
        verification = self.verification_toolset.verify_citations(
            {"citations": citations}
        )
        summary = verification.get("summary", {})
        failures = [
            r.get("claim_id")
            for r in verification.get("results", [])
            if r.get("severity") in ("dead", "major_fabrication")
        ]

        gaps: list[str] = []
        if ungrounded:
            gaps.append(
                "These citations are not grounded in any tool result -- remove "
                f"them or cite a retrieved work: {', '.join(ungrounded)}."
            )
        if failures:
            gaps.append(
                "These citations failed verification (dead DOI or fabricated "
                f"metadata): {', '.join(str(f) for f in failures)}."
            )
        ok = not ungrounded and not failures
        return {
            "ok": ok,
            "ungrounded": ungrounded,
            "failures": failures,
            "summary": summary,
            "gaps": gaps,
        }

    def _gate_scope(self, sections: dict) -> dict:
        """Light, honest scope check.

        We cannot deterministically judge whether a plan fits a budget -- the
        panel's c2 does that -- but we can require the scope & timeline section to
        commit to concrete numbers (a duration or dollar figure) rather than
        hand-wave the fit.
        """
        text = str(sections.get("scope_timeline") or "")
        has_number = bool(re.search(r"\d", text))
        gaps = []
        if not has_number:
            gaps.append(
                "State the budget and timeline concretely (dollar amount and "
                "duration) in the scope & timeline section."
            )
        return {"ok": has_number, "has_number": has_number, "gaps": gaps}

    def _gate_panel(self, submitted: dict) -> dict:
        proposal_text = str(submitted.get("plain_text") or "")
        rollup = self.panel.score(
            proposal_text,
            context=self._judge_context(submitted),
        )
        overall = rollup.get("overall", 0)
        ok = overall >= self.panel_threshold
        gaps = []
        if not ok:
            gaps.append(
                f"The judge panel scored this {overall} overall, below the "
                f"{self.panel_threshold} bar. Close these gaps: "
                + "; ".join(rollup.get("gaps", []) or ["raise overall quality"])
                + "."
            )
        return {
            "ok": ok,
            "overall": overall,
            "scores": rollup.get("scores"),
            "threshold": self.panel_threshold,
            "rollup": rollup,
            "gaps": gaps,
        }

    def _judge_tool_context(self, args: dict) -> dict:
        """Server-side judge context for the agent-facing ``judge_proposal`` tool."""
        return self._judge_context({"citations": args.get("citations") or []})

    def _judge_context(self, submitted: dict | None = None) -> dict:
        """Evidence judges need for RFP fit, budget fit, credibility, and novelty."""
        submitted = submitted or {}
        return {
            "rfp": _compact_rfp_context(
                self.rfp_context,
                max_chars=self.max_judge_rfp_chars,
            ),
            "researcher_profile": _compact_profile_context(
                self.expert.profile,
                max_works=self.max_judge_works,
                max_abstract_chars=self.max_judge_abstract_chars,
            ),
            "citations": _compact_citations(submitted.get("citations")),
            "grounded_source_urls": sorted(self._grounded_urls()),
        }

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
        note = self._write_note(self.submitted)
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

    def _fail(self) -> dict:
        if self.submitted is None:
            message = "agent did not submit a proposal"
        elif self.rounds_used >= self.max_rounds:
            message = f"gates not cleared within {self.max_rounds} rounds"
        else:
            message = "agent ended without an accepted proposal"
        self.draft.final_scores = self.final_scores
        self.draft.gate_report = self.last_gate_report
        self.draft.rounds_used = self.rounds_used
        # Persist the rejected draft so a failed run is still inspectable: a
        # FAILED run never writes a Note, so this is the only place its content
        # survives. ``{}`` when the agent never submitted.
        self.draft.last_submission = self.submitted or {}
        self.draft.status = ProposalDraft.Status.FAILED
        self.draft.error_message = message
        self.draft.save()
        return {
            "status": ProposalDraft.Status.FAILED,
            "proposal_draft_id": self.draft.id,
            "rounds_used": self.rounds_used,
            "gate_report": self.last_gate_report,
            "last_submission": self.draft.last_submission,
            "error_message": message,
        }

    @transaction.atomic
    def _write_note(self, submitted: dict) -> Note:
        """Create the Note directly (headless: no owner/org, no notifications).

        The view paths require an auth user + org and fire org-scoped websocket
        notifications that would dereference a null org, so we create the rows
        directly. The ``NoteContent`` post_save signal sets ``note.latest_version``.
        """
        sections = submitted.get("sections") or {}
        title = str(sections.get("title") or "").strip() or "Untitled proposal"
        unified_document = ResearchhubUnifiedDocument.objects.create(document_type=NOTE)
        note = Note.objects.create(
            created_by=None,
            organization=None,
            title=title,
            unified_document=unified_document,
        )
        prosemirror = submitted.get("prosemirror")
        NoteContent.objects.create(
            note=note,
            # Store the ProseMirror doc as a JSON-encoded string, matching the
            # shape the view path persists (the frontend POSTs ``full_json`` as a
            # string) and the editor's ``JSON.parse(contentJson)`` expects. A raw
            # object round-trips as an object and breaks note loading.
            json=json.dumps(prosemirror) if prosemirror is not None else None,
            plain_text=str(submitted.get("plain_text") or ""),
        )
        note.refresh_from_db()
        return note

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


def _prosemirror_ok(doc) -> bool:
    """Minimal ProseMirror shape check: a doc node with non-empty content."""
    return (
        isinstance(doc, dict)
        and doc.get("type") == "doc"
        and isinstance(doc.get("content"), list)
        and len(doc["content"]) > 0
    )


def run_proposal_draft(
    search_expert_id,
    *,
    progress_callback=None,
    provider=None,
    panel: ProposalJudgePanel | None = None,
    oa_client: OpenAlex | None = None,
) -> dict:
    """Run a headless proposal-drafting job for one ``SearchExpert``.

    Creates a ``ProposalDraft``, builds the agent, runs the bounded
    draft -> critique -> verify -> revise loop with a deterministic gate before
    stop, and writes the verified proposal as a ``Note``. Returns a result dict
    carrying the final status, the gate report, and (on success) the note id.

    ``provider`` / ``panel`` / ``oa_client`` are injectable for tests; in
    production they default to the real Bedrock provider, judge panel, and
    OpenAlex client.
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
    )
    return runner.run()
