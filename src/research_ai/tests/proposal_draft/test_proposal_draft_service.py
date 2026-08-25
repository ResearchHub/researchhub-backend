"""Driver tests for the proposal-draft run.

The agent loop is driven by a scripted/always-submitting fake provider so a whole
run is deterministic: the model "submits" a payload, and the driver's gates --
the real code under test -- decide whether the submit is accepted, fed back, or
exhausts the round budget. All LLM providers and external APIs are mocked at the
client boundary; no network.
"""

import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.utils import timezone

from note.models import Note
from purchase.models import Grant
from research_ai.models import (
    AgentExecution,
    AgentExecutionMessage,
    Expert,
    ExpertSearch,
    ProposalDraft,
    SearchExpert,
)
from research_ai.services.agent import LLMProvider
from research_ai.services.agent.types import (
    AssistantTurn,
    StopReason,
    TextBlock,
    ToolUseBlock,
)
from research_ai.services.agent_persistence import (
    AgentConversationService,
    AgentExecutionService,
    AgentRetentionService,
    NoteAgentConversationService,
)
from research_ai.services.proposal_draft import run_proposal_draft
from research_ai.services.proposal_draft.cancel_service import (
    ProposalDraftCancelledError,
    ProposalDraftCancelService,
)
from research_ai.services.proposal_draft.draft_recorder import DraftRecorder
from research_ai.services.proposal_draft.runner import (
    PROFILE_SCHEMA_VERSION,
    _ProposalDraftRunner,
)
from research_ai.services.proposal_draft.tools.assembly import assemble_proposal
from researchhub_access_group.constants import ADMIN, NO_ACCESS
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import GRANT
from user.tests.helpers import create_random_default_user

_CRITERIA = ("c1", "c2", "c3", "c4", "c5", "c6", "c7")


class _FakeOpenAlex:
    """Stand-in for ``utils.openalex.OpenAlex`` keyed by DOI."""

    def __init__(self, by_doi=None):
        self._by_doi = by_doi or {}

    def get_work_by_doi(self, doi):
        return self._by_doi.get(doi)


class _FakePanel:
    """A judge panel whose ``score`` returns a fixed rollup."""

    def __init__(self, overall=5, gaps=None, scores=None):
        self.model_ids = ["fake-judge"]
        self._overall = overall
        self._gaps = gaps or []
        self._scores = scores
        self.contexts = []

    def score(self, _proposal, *, context=None):
        self.contexts.append(context)
        return {
            "scores": self._scores or dict.fromkeys(_CRITERIA, self._overall),
            "overall": self._overall,
            "gaps": self._gaps,
        }

    def pairwise(self, _a, _b, *, context=None):
        return "A"


class _SequencePanel:
    """Panel whose overall walks a fixed sequence (the last value repeats)."""

    def __init__(self, overalls, gaps=None):
        self.model_ids = ["fake-judge"]
        self._overalls = list(overalls)
        self._gaps = gaps or ["raise overall quality"]
        self.calls = 0

    def score(self, _proposal, *, context=None):
        overall = self._overalls[min(self.calls, len(self._overalls) - 1)]
        self.calls += 1
        return {
            "scores": dict.fromkeys(_CRITERIA, overall),
            "overall": overall,
            "gaps": self._gaps,
        }

    def pairwise(self, _a, _b, *, context=None):
        return "A"


class _ScriptedProvider(LLMProvider):
    """Returns queued ``AssistantTurn``s, then ends the turn in plain text."""

    def __init__(self, turns):
        self._turns = list(turns)
        self.call_count = 0

    def render_tools(self, _tools):
        return {"tools": []}

    def complete(self, **_kwargs):
        self.call_count += 1
        if self._turns:
            return self._turns.pop(0)
        return AssistantTurn(
            text_blocks=[TextBlock(text="done")],
            tool_calls=[],
            stop_reason=StopReason.END_TURN,
        )


class _AlwaysSubmitProvider(LLMProvider):
    """Submits the same payload on every turn (drives the round-budget bound)."""

    def __init__(self, payload):
        self._payload = payload
        self.call_count = 0

    def render_tools(self, _tools):
        return {"tools": []}

    def complete(self, **_kwargs):
        self.call_count += 1
        return AssistantTurn(
            text_blocks=[],
            tool_calls=[
                ToolUseBlock(
                    id=f"submit-{self.call_count}",
                    name="submit_proposal",
                    input=self._payload,
                )
            ],
            stop_reason=StopReason.TOOL_USE,
        )


class _SequenceSubmitProvider(LLMProvider):
    """Submits a distinct payload per round (the last payload repeats)."""

    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.call_count = 0

    def render_tools(self, _tools):
        return {"tools": []}

    def complete(self, **_kwargs):
        payload = self._payloads[min(self.call_count, len(self._payloads) - 1)]
        self.call_count += 1
        return AssistantTurn(
            text_blocks=[],
            tool_calls=[
                ToolUseBlock(
                    id=f"submit-{self.call_count}",
                    name="submit_proposal",
                    input=payload,
                )
            ],
            stop_reason=StopReason.TOOL_USE,
        )


def _submit_turn(payload):
    return AssistantTurn(
        text_blocks=[],
        tool_calls=[ToolUseBlock(id="submit-1", name="submit_proposal", input=payload)],
        stop_reason=StopReason.TOOL_USE,
    )


# Filler prose so the assembled plain_text clears the 250-word minimum -- the
# server now derives plain_text from these sections, so they must carry the words.
_FILLER = (
    "We will measure X under Y conditions across biological replicates, "
    "controlling for Z and reporting effect sizes with confidence intervals. "
) * 20


def _clean_sections(title="A Study of Folding"):
    return {
        "title": title,
        "background": "We hypothesize that X drives Y in measurable ways.",
        "preliminary_data": "Pilot work shows the trend. " + _FILLER,
        "aims": [
            {
                "title": "Measure X",
                "body": "We will measure X under Y conditions. " + _FILLER,
            }
        ],
        "limitations": (
            "The selected model bounds inference to Y conditions. Low signal "
            "is a material pitfall; if the prespecified threshold is missed, "
            "the analysis will use aggregate measurements and narrow the claim."
        ),
        "why_this_team": "Jane Smith has published on protein folding.",
        "budget": "The $50,000 award covers compute and storage.",
        "timeline": "The plan runs 24 months with monthly milestones.",
    }


def _clean_payload(citations=None):
    # The agent submits sections (+ citations) only; the server assembles the
    # readable text and ProseMirror doc from the sections.
    return {
        "sections": _clean_sections(),
        "citations": citations or [],
    }


class ProposalDraftServiceTests(TestCase):
    def setUp(self):
        # Arrange: GRANT post + Grant + Expert (pre-built profile) + SearchExpert.
        self.user = create_random_default_user("proposer")
        self.post = create_post(
            created_by=self.user,
            document_type=GRANT,
            renderable_text="Full RFP body: fund work on protein folding.",
        )
        self.grant = Grant.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            amount=Decimal("50000.00"),
            currency="USD",
            organization="National Science Foundation",
            short_title="Protein Folding RFP",
            description="Research grant for protein folding work",
            status=Grant.OPEN,
            end_date=timezone.now() + timedelta(days=365),
        )
        self.expert = Expert.objects.create(
            email="jane@example.edu",
            first_name="Jane",
            last_name="Smith",
            profile={
                # Current schema so the run reuses it instead of rebuilding.
                "schema_version": PROFILE_SCHEMA_VERSION,
                "resolution": {"openalex_author_id": "A1", "confidence": 0.9},
                "works": [
                    {
                        "title": "Folding",
                        "source_url": "https://doi.org/10.1/a",
                        "pdf_url": "https://example.edu/a.pdf",
                    }
                ],
            },
        )
        self.expert_search = ExpertSearch.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            query="protein folding",
        )
        self.search_expert = SearchExpert.objects.create(
            expert_search=self.expert_search,
            expert=self.expert,
        )

    # -- clean submit writes the Note -------------------------------------

    def test_clean_submit_writes_note(self):
        # Arrange: one clean submit; panel clears the threshold; no citations.
        provider = _ScriptedProvider([_submit_turn(_clean_payload())])
        panel = _FakePanel(overall=5)
        conversation_service = Mock(wraps=AgentConversationService())
        execution_service = Mock(wraps=AgentExecutionService())
        note_conversation_service = Mock(wraps=NoteAgentConversationService())

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            panel=panel,
            oa_client=_FakeOpenAlex(),
            conversation_service=conversation_service,
            execution_service=execution_service,
            note_conversation_service=note_conversation_service,
        )

        # Assert: status, the Note + content, and the draft linkage.
        self.assertEqual(result["status"], ProposalDraft.Status.COMPLETED)
        note = Note.objects.get(id=result["note_id"])
        self.assertEqual(note.title, "A Study of Folding")
        # A run without a pre-created draft has no triggering user, so the
        # note stays ownerless (system/automatic run).
        self.assertIsNone(note.created_by)
        self.assertIsNone(note.organization)
        self.assertIsNotNone(note.latest_version)  # set by the post_save signal
        # json is stored as a JSON-encoded string (matching the view path and
        # what the editor's JSON.parse expects), not a raw object. The server
        # assembles the doc + plain text from the submitted sections.
        expected_plain, expected_doc = assemble_proposal(_clean_sections())
        self.assertIsInstance(note.latest_version.json, str)
        self.assertEqual(json.loads(note.latest_version.json), expected_doc)
        self.assertEqual(note.latest_version.plain_text, expected_plain)

        draft = ProposalDraft.objects.get(id=result["proposal_draft_id"])
        self.assertEqual(draft.note_id, note.id)
        self.assertEqual(draft.status, ProposalDraft.Status.COMPLETED)
        self.assertEqual(draft.step, ProposalDraft.Step.DONE)
        self.assertEqual(draft.final_scores["overall"], 5)
        self.assertEqual(draft.rounds_used, 1)
        self.assertIsNotNone(draft.agent_conversation_id)
        self.assertEqual(draft.agent_conversation.workflow, "proposal_draft")
        self.assertEqual(draft.agent_conversation.chat_messages.count(), 0)
        execution = draft.agent_conversation.executions.get()
        self.assertEqual(execution.status, AgentExecution.Status.SUCCEEDED)
        self.assertEqual(
            execution.messages.first().provenance,
            AgentExecutionMessage.Provenance.BACKEND,
        )
        self.assertEqual(draft.agent_conversation.proposal_draft, draft)
        self.assertEqual(execution.configuration, draft.run_config)
        self.assertEqual(
            list(NoteAgentConversationService().for_note(note)),
            [draft.agent_conversation],
        )
        conversation_service.create.assert_called_once_with(
            user=None,
            workflow="proposal_draft",
        )
        execution_service.start.assert_called_once()
        note_conversation_service.attach.assert_called_once_with(
            draft.agent_conversation,
            note,
        )
        self.assertTrue(panel.contexts)  # panel was scored at least once
        self.assertEqual(
            panel.contexts[0]["rfp"]["organization"],
            "National Science Foundation",
        )
        self.assertEqual(
            panel.contexts[0]["researcher_profile"]["works"][0]["source_url"],
            "https://doi.org/10.1/a",
        )

        # Debug retention removes the trace, never the shipped proposal.
        AgentRetentionService().delete_conversation_debug(draft.agent_conversation)
        draft.refresh_from_db()
        self.assertEqual(draft.status, ProposalDraft.Status.COMPLETED)
        self.assertTrue(Note.objects.filter(id=note.id).exists())
        retained_execution = draft.agent_conversation.executions.get()
        self.assertEqual(retained_execution.messages.count(), 0)
        self.assertGreater(retained_execution.context_messages.count(), 0)
        self.assertEqual(
            note.agent_conversation_links.get().conversation_id,
            draft.agent_conversation_id,
        )

    def test_selected_model_resolves_provider_and_lands_in_run_config(self):
        # Arrange: a user-selected model ref and no injected provider, so the
        # runner must resolve the ref itself.
        provider = _ScriptedProvider([_submit_turn(_clean_payload())])

        # Act
        with patch(
            "research_ai.services.proposal_draft.runner.resolve_provider",
            return_value=provider,
        ) as resolve:
            result = run_proposal_draft(
                self.search_expert.id,
                model_ref="openrouter:openai/gpt-5.6-sol",
                panel=_FakePanel(overall=5),
                oa_client=_FakeOpenAlex(),
            )

        # Assert: the selection is what gets resolved, recorded on the draft,
        # and snapshotted as the run's generator.
        resolve.assert_called_once_with(
            "openrouter:openai/gpt-5.6-sol",
            native_tools=frozenset({"web_search"}),
        )
        self.assertEqual(result["status"], ProposalDraft.Status.COMPLETED)
        draft = ProposalDraft.objects.get(id=result["proposal_draft_id"])
        self.assertEqual(draft.model_ref, "openrouter:openai/gpt-5.6-sol")
        self.assertEqual(
            draft.run_config["generator_model_id"], "openrouter:openai/gpt-5.6-sol"
        )

    def test_default_judge_roster_follows_the_selected_model(self):
        # Arrange: no injected panel, so the default single-judge roster is
        # built from the selected model. The provider never submits, so no
        # judge is ever actually called (roster ids resolve without clients).
        provider = _ScriptedProvider([])

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            model_ref="openrouter:openai/gpt-5.6-sol",
            oa_client=_FakeOpenAlex(),
        )

        # Assert
        draft = ProposalDraft.objects.get(id=result["proposal_draft_id"])
        self.assertEqual(
            draft.run_config["judge_roster"], ["openrouter:openai/gpt-5.6-sol"]
        )

    def test_note_attachment_failure_does_not_break_proposal(self):
        # Arrange
        provider = _ScriptedProvider([_submit_turn(_clean_payload())])
        note_conversation_service = Mock(spec=NoteAgentConversationService)
        note_conversation_service.attach.side_effect = RuntimeError(
            "association database unavailable"
        )

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            panel=_FakePanel(overall=5),
            oa_client=_FakeOpenAlex(),
            note_conversation_service=note_conversation_service,
        )

        # Assert
        draft = ProposalDraft.objects.get(id=result["proposal_draft_id"])
        self.assertEqual(result["status"], ProposalDraft.Status.COMPLETED)
        self.assertEqual(draft.status, ProposalDraft.Status.COMPLETED)
        self.assertIsNotNone(draft.note_id)
        self.assertIsNotNone(draft.agent_conversation_id)
        self.assertFalse(draft.note.agent_conversation_links.exists())
        self.assertEqual(
            list(NoteAgentConversationService().for_note(draft.note)),
            [draft.agent_conversation],
        )

    def test_trace_initialization_failure_does_not_break_proposal(self):
        # Arrange
        provider = _ScriptedProvider([_submit_turn(_clean_payload())])
        execution_service = Mock(spec=AgentExecutionService)
        execution_service.start.side_effect = RuntimeError("trace database unavailable")

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            panel=_FakePanel(overall=5),
            oa_client=_FakeOpenAlex(),
            execution_service=execution_service,
        )

        # Assert
        self.assertEqual(result["status"], ProposalDraft.Status.COMPLETED)
        self.assertTrue(Note.objects.filter(id=result["note_id"]).exists())

    @override_settings(RESEARCH_AI_PROPOSAL_MAX_ROUNDS=1)
    def test_missing_limitations_section_is_blocked(self):
        # Arrange: otherwise-valid sections omit the required risk analysis.
        sections = _clean_sections()
        sections.pop("limitations")
        provider = _AlwaysSubmitProvider({"sections": sections, "citations": []})

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            panel=_FakePanel(overall=5),
            oa_client=_FakeOpenAlex(),
        )

        # Assert
        self.assertEqual(result["status"], ProposalDraft.Status.FAILED)
        sections_report = result["gate_report"]["sections"]
        self.assertFalse(sections_report["ok"])
        self.assertIn(
            "limitations, pitfalls & alternative approaches",
            sections_report["missing"],
        )
        self.assertEqual(Note.objects.count(), 0)

    def test_run_with_pre_created_draft_reuses_row(self):
        # Arrange
        draft = ProposalDraft.objects.create(
            search_expert=self.search_expert,
            created_by=self.user,
            status=ProposalDraft.Status.PENDING,
            step=ProposalDraft.Step.QUEUED,
        )
        provider = _ScriptedProvider([_submit_turn(_clean_payload())])
        panel = _FakePanel(overall=5)

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            draft_id=draft.id,
            provider=provider,
            panel=panel,
            oa_client=_FakeOpenAlex(),
        )

        # Assert
        self.assertEqual(result["proposal_draft_id"], draft.id)
        self.assertEqual(ProposalDraft.objects.count(), 1)
        draft.refresh_from_db()
        self.assertEqual(draft.status, ProposalDraft.Status.COMPLETED)
        self.assertEqual(draft.created_by, self.user)

        # The note lands privately in the triggering user's notebook: owned
        # by them, in their personal org, admin for the user but no org access.
        note = Note.objects.get(id=result["note_id"])
        self.assertEqual(note.created_by, self.user)
        self.assertEqual(note.organization, self.user.organization)
        permissions = note.unified_document.permissions
        self.assertTrue(
            permissions.filter(
                user=self.user, organization__isnull=True, access_type=ADMIN
            ).exists()
        )
        self.assertTrue(
            permissions.filter(
                organization=self.user.organization, access_type=NO_ACCESS
            ).exists()
        )

    # -- a major_fabrication submit is blocked, gaps fed back -------------

    def test_major_fabrication_submit_is_blocked_and_loop_continues(self):
        # Arrange: a citation whose DOI resolves to a clearly different paper.
        citations = [
            {
                "claim_id": "k1",
                "doi": "10.1/x",
                "title": "Protein Folding Dynamics",
                "authors": ["Jane Smith"],
            }
        ]
        oa = _FakeOpenAlex(
            {
                "10.1/x": {
                    "display_name": "Quantum Gravity in 2D",
                    "publication_year": 2019,
                    "doi": "https://doi.org/10.1/x",
                    "id": "https://openalex.org/W9",
                    "authorships": [{"author": {"display_name": "Alan Turing"}}],
                }
            }
        )
        provider = _ScriptedProvider([_submit_turn(_clean_payload(citations))])

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            panel=_FakePanel(overall=5),
            oa_client=oa,
        )

        # Assert: blocked (not accepted), the loop ran another turn after the
        # rejected submit, and the report names the fabrication.
        self.assertEqual(result["status"], ProposalDraft.Status.FAILED)
        self.assertGreaterEqual(provider.call_count, 2)
        report = result["gate_report"]
        self.assertFalse(report["citations"]["ok"])
        self.assertEqual(report["citations"]["summary"]["major"], 1)
        self.assertEqual(Note.objects.count(), 0)

    # -- a below-threshold panel submit is blocked ------------------------

    def test_low_panel_score_submit_is_blocked(self):
        # Arrange: a clean draft, but the panel scores below the threshold.
        provider = _ScriptedProvider([_submit_turn(_clean_payload())])

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            panel=_FakePanel(overall=2),
            oa_client=_FakeOpenAlex(),
        )

        # Assert
        self.assertEqual(result["status"], ProposalDraft.Status.FAILED)
        self.assertGreaterEqual(provider.call_count, 2)
        self.assertFalse(result["gate_report"]["panel"]["ok"])
        self.assertEqual(result["gate_report"]["panel"]["overall"], 2)
        self.assertEqual(Note.objects.count(), 0)

        # The rejected draft is persisted for inspection even though no Note
        # was written.
        draft = ProposalDraft.objects.get(id=result["proposal_draft_id"])
        self.assertEqual(
            draft.last_submission["sections"]["title"], "A Study of Folding"
        )
        self.assertEqual(result["last_submission"], draft.last_submission)

    def test_low_style_score_is_blocked_when_overall_score_passes(self):
        # Arrange: substance lifts the mean over the general panel bar, but the
        # scientific writing voice remains recognizably model-shaped.
        scores = dict.fromkeys(_CRITERIA, 5)
        scores["c7"] = 3
        provider = _ScriptedProvider([_submit_turn(_clean_payload())])
        panel = _FakePanel(
            overall=4.71,
            scores=scores,
            gaps=[
                "c7: 'This innovative study' — vague abstraction; name the "
                "measurement instead."
            ],
        )

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            panel=panel,
            oa_client=_FakeOpenAlex(),
        )

        # Assert: c7 has its own floor, so stronger criteria cannot mask it.
        self.assertEqual(result["status"], ProposalDraft.Status.FAILED)
        panel_report = result["gate_report"]["panel"]
        self.assertFalse(panel_report["ok"])
        self.assertEqual(panel_report["overall"], 4.71)
        self.assertEqual(panel_report["style_score"], 3)
        self.assertEqual(panel_report["style_threshold"], 4.0)
        self.assertIn("This innovative study", panel_report["gaps"][0])
        self.assertEqual(Note.objects.count(), 0)

    # -- too many aims for the award size is blocked ----------------------

    def test_over_scoped_aims_are_blocked(self):
        # Arrange: the $50k award funds at most two aims, but the draft has three.
        sections = _clean_sections()
        sections["aims"] = [
            {"title": f"Aim {i}", "body": "We will measure X. " + _FILLER}
            for i in range(1, 4)
        ]
        payload = {"sections": sections, "citations": []}
        provider = _ScriptedProvider([_submit_turn(payload)])

        # Act: the panel would pass (overall 5), so scope is the only blocker.
        result = run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            panel=_FakePanel(overall=5),
            oa_client=_FakeOpenAlex(),
        )

        # Assert: blocked on scope, the loop revised, and no Note was written.
        self.assertEqual(result["status"], ProposalDraft.Status.FAILED)
        self.assertGreaterEqual(provider.call_count, 2)
        scope = result["gate_report"]["scope"]
        self.assertFalse(scope["ok"])
        self.assertEqual(scope["max_aims"], 2)
        self.assertEqual(scope["aims"], 3)
        # The rejection names the award in the same format the prompt uses.
        self.assertIn("This award ($50,000) funds at most 2", scope["gaps"][0])
        self.assertEqual(Note.objects.count(), 0)

    # -- exhausting the round budget fails with a gate report -------------

    @override_settings(RESEARCH_AI_PROPOSAL_MAX_ROUNDS=2)
    def test_max_rounds_exhaustion_fails(self):
        # Arrange: every submit fails the panel; the provider never stops on its
        # own, so the round budget is what ends the run.
        provider = _AlwaysSubmitProvider(_clean_payload())

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            panel=_FakePanel(overall=2),
            oa_client=_FakeOpenAlex(),
        )

        # Assert
        self.assertEqual(result["status"], ProposalDraft.Status.FAILED)
        self.assertEqual(provider.call_count, 2)
        draft = ProposalDraft.objects.get(id=result["proposal_draft_id"])
        self.assertEqual(draft.status, ProposalDraft.Status.FAILED)
        self.assertEqual(draft.rounds_used, 2)
        self.assertTrue(draft.gate_report)  # populated for diagnosis
        self.assertEqual(
            draft.last_submission["sections"]["title"], "A Study of Folding"
        )
        self.assertEqual(Note.objects.count(), 0)

    # -- each round is persisted before the loop reaches a terminal path --

    @override_settings(RESEARCH_AI_PROPOSAL_MAX_ROUNDS=2)
    def test_round_state_persists_before_terminal(self):
        # Arrange: the panel always rejects so the loop runs a full round before
        # it exhausts the budget. A provider that snapshots the DB row on each
        # turn lets us prove round 1 was written before the terminal _fail.
        snapshots = []
        search_expert_id = self.search_expert.id

        class _SnapshottingProvider(_AlwaysSubmitProvider):
            def complete(self, **kwargs):
                draft = ProposalDraft.objects.filter(
                    search_expert_id=search_expert_id
                ).first()
                if draft is not None:
                    snapshots.append((draft.rounds_used, dict(draft.last_submission)))
                return super().complete(**kwargs)

        provider = _SnapshottingProvider(_clean_payload())

        # Act
        run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            panel=_FakePanel(overall=2),
            oa_client=_FakeOpenAlex(),
        )

        # Assert: entering round 2, round 1's submission and count are already
        # on the row -- not the zeroed defaults that would show pre-persist.
        self.assertGreaterEqual(len(snapshots), 2)
        rounds_after_first, submission_after_first = snapshots[1]
        self.assertEqual(rounds_after_first, 1)
        self.assertEqual(
            submission_after_first["sections"]["title"], "A Study of Folding"
        )

    # -- a run that never submits persists an empty last_submission ------

    def test_no_submit_persists_empty_last_submission(self):
        # Arrange: the agent answers in plain text without ever submitting.
        provider = _ScriptedProvider([])

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            panel=_FakePanel(overall=5),
            oa_client=_FakeOpenAlex(),
        )

        # Assert: failed for "did not submit", and last_submission is empty.
        self.assertEqual(result["status"], ProposalDraft.Status.FAILED)
        self.assertIn("did not submit", result["error_message"])
        draft = ProposalDraft.objects.get(id=result["proposal_draft_id"])
        self.assertEqual(draft.last_submission, {})

    # -- the web_search tool is composed into the agent toolset ----------

    def test_web_search_tool_is_wired_into_the_agent(self):
        # Arrange: a runner with an injected web-search client.
        draft = ProposalDraft.objects.create(
            search_expert=self.search_expert,
            status=ProposalDraft.Status.PENDING,
            step=ProposalDraft.Step.QUEUED,
        )
        sentinel = object()
        runner = _ProposalDraftRunner(
            self.search_expert,
            draft,
            oa_client=_FakeOpenAlex(),
            web_search_client=sentinel,
        )

        # Act
        toolset = runner._compose_toolset(_ScriptedProvider([]))

        # Assert: the tool is exposed to the agent, and the injected client is
        # used, with its own provenance kept separate from citation grounding.
        self.assertIn("web_search", toolset.names)
        self.assertIs(runner.web_search_toolset._client, sentinel)
        self.assertIsNot(runner.web_search_toolset.provenance, runner.provenance)

    def test_provider_with_native_search_drops_the_local_web_search_tool(self):
        # Arrange: a provider that runs web search itself (Claude Platform).
        class _NativeSearchProvider(_ScriptedProvider):
            @property
            def native_tool_names(self):
                return frozenset({"web_search"})

        draft = ProposalDraft.objects.create(
            search_expert=self.search_expert,
            status=ProposalDraft.Status.PENDING,
            step=ProposalDraft.Step.QUEUED,
        )
        runner = _ProposalDraftRunner(
            self.search_expert, draft, oa_client=_FakeOpenAlex()
        )

        # Act
        toolset = runner._compose_toolset(_NativeSearchProvider([]))

        # Assert: the name is left free for the provider's own declaration --
        # two tools sharing one name is a request error -- and nothing else
        # about the toolset changes.
        self.assertNotIn("web_search", toolset.names)
        self.assertIn("search_works", toolset.names)
        self.assertIn("verify_citations", toolset.names)
        self.assertIn("submit_proposal", toolset.names)

    # -- a flat panel score below the bar stops the loop early ------------

    @override_settings(
        RESEARCH_AI_PROPOSAL_MAX_ROUNDS=8,
        RESEARCH_AI_PROPOSAL_PLATEAU_PATIENCE=3,
    )
    def test_panel_plateau_stops_early_before_round_budget(self):
        # Arrange: every submit scores a constant 2 (below the bar) -- no round
        # improves on the first, so the plateau guard, not the 8-round budget,
        # ends the run.
        provider = _AlwaysSubmitProvider(_clean_payload())

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            panel=_FakePanel(overall=2),
            oa_client=_FakeOpenAlex(),
        )

        # Assert: stopped at round 4 (round 1 sets the best, then patience=3
        # flat rounds), well short of the 8-round budget, with the plateau named
        # in the failure message.
        self.assertEqual(result["status"], ProposalDraft.Status.FAILED)
        self.assertEqual(provider.call_count, 4)
        self.assertIn("plateau", result["error_message"])
        self.assertEqual(Note.objects.count(), 0)

    # -- an improving panel resets the plateau counter, run keeps going ---

    @override_settings(
        RESEARCH_AI_PROPOSAL_MAX_ROUNDS=10,
        RESEARCH_AI_PROPOSAL_PLATEAU_PATIENCE=3,
    )
    def test_improving_panel_is_not_cut_short_by_plateau(self):
        # Arrange: the score climbs 2 -> 3 -> 3.5 then flatlines. The early gains
        # reset the counter, so the run runs past round 4 and only plateaus once
        # the score has been flat for three rounds (rounds 4, 5, 6).
        provider = _AlwaysSubmitProvider(_clean_payload())
        panel = _SequencePanel([2, 3, 3.5])

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            panel=panel,
            oa_client=_FakeOpenAlex(),
        )

        # Assert: it did not stop at round 4; the early gains reset the counter
        # so it ran to round 6, then plateaued.
        self.assertEqual(result["status"], ProposalDraft.Status.FAILED)
        self.assertEqual(provider.call_count, 6)
        self.assertIn("plateau", result["error_message"])

    # -- clearing the bar does not stop the loop; it runs to plateau ------

    @override_settings(
        RESEARCH_AI_PROPOSAL_MAX_ROUNDS=8,
        RESEARCH_AI_PROPOSAL_PLATEAU_PATIENCE=3,
    )
    def test_passing_panel_keeps_refining_until_plateau_then_completes(self):
        # Arrange: every submit clears the 4.0 bar at a constant 4, so the run
        # must NOT stop at round 1 -- it keeps revising to try to raise the score
        # and only stops when the flat score plateaus.
        provider = _AlwaysSubmitProvider(_clean_payload())
        panel = _FakePanel(overall=4)

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            panel=panel,
            oa_client=_FakeOpenAlex(),
        )

        # Assert: round 1 sets the best, then patience=3 flat rounds -> stops at
        # round 4 (short of the 8-round budget), and still COMPLETES because a
        # round cleared every gate, shipping that draft as a Note.
        self.assertEqual(result["status"], ProposalDraft.Status.COMPLETED)
        self.assertEqual(provider.call_count, 4)
        self.assertEqual(result["final_scores"]["overall"], 4)
        self.assertEqual(Note.objects.count(), 1)
        draft = ProposalDraft.objects.get(id=result["proposal_draft_id"])
        self.assertEqual(draft.status, ProposalDraft.Status.COMPLETED)
        self.assertEqual(draft.rounds_used, 4)

    @override_settings(
        RESEARCH_AI_PROPOSAL_MAX_ROUNDS=8,
        RESEARCH_AI_PROPOSAL_PLATEAU_PATIENCE=3,
    )
    def test_completed_run_ships_the_highest_scoring_accepted_round(self):
        # Arrange: the score climbs above the bar (4 -> 4.5) then flatlines. The
        # run should keep the higher round and ship it, not the first one that
        # merely cleared the bar.
        provider = _AlwaysSubmitProvider(_clean_payload())
        panel = _SequencePanel([4, 4.5], gaps=[])

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            panel=panel,
            oa_client=_FakeOpenAlex(),
        )

        # Assert: the 4.5 round wins; the run completes on plateau (round 5) with
        # the peak score persisted.
        self.assertEqual(result["status"], ProposalDraft.Status.COMPLETED)
        self.assertEqual(provider.call_count, 5)
        self.assertEqual(result["final_scores"]["overall"], 4.5)
        draft = ProposalDraft.objects.get(id=result["proposal_draft_id"])
        self.assertEqual(draft.final_scores["overall"], 4.5)

    # -- a failed run persists the best draft, not the last ----------------

    @override_settings(
        RESEARCH_AI_PROPOSAL_MAX_ROUNDS=8,
        RESEARCH_AI_PROPOSAL_PLATEAU_PATIENCE=3,
    )
    def test_failed_run_persists_best_scoring_draft_not_last(self):
        # Arrange: round 1 scores the peak (3.5), then the score regresses to 3
        # and flatlines, so the plateau guard stops the loop on a round whose
        # draft is worse than the peak. Each round submits a differently-titled
        # payload so the persisted draft is identifiable.
        peak = _clean_payload()
        peak["sections"]["title"] = "Peak Draft"
        regressed = _clean_payload()
        regressed["sections"]["title"] = "Regressed Draft"
        provider = _SequenceSubmitProvider([peak, regressed])
        panel = _SequencePanel([3.5, 3])

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            panel=panel,
            oa_client=_FakeOpenAlex(),
        )
        draft = ProposalDraft.objects.get(id=result["proposal_draft_id"])

        # Assert: plateau-stopped after the regression, but the persisted draft,
        # gate report, and scores are the round-1 peak -- not the worse final
        # round -- and the result dict mirrors what was persisted.
        self.assertEqual(result["status"], ProposalDraft.Status.FAILED)
        self.assertIn("plateau", result["error_message"])
        self.assertEqual(draft.last_submission["sections"]["title"], "Peak Draft")
        self.assertEqual(draft.gate_report["panel"]["overall"], 3.5)
        self.assertEqual(draft.final_scores["overall"], 3.5)
        self.assertEqual(result["last_submission"], draft.last_submission)
        self.assertEqual(result["gate_report"], draft.gate_report)

    # -- hitting the core iteration cap is a distinct, recorded failure ---

    @override_settings(
        RESEARCH_AI_PROPOSAL_MAX_ROUNDS=10,
        RESEARCH_AI_PROPOSAL_MAX_ITERATIONS=3,
        RESEARCH_AI_PROPOSAL_PLATEAU_PATIENCE=5,
    )
    def test_iteration_cap_failure_is_distinct_and_recorded(self):
        # Arrange: submits forever against a failing panel, but the iteration cap
        # (3) bites before the round budget (10) or the plateau patience (5).
        provider = _AlwaysSubmitProvider(_clean_payload())

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            panel=_FakePanel(overall=2),
            oa_client=_FakeOpenAlex(),
        )

        # Assert: the failure names the iteration cap (not the generic message).
        self.assertEqual(result["status"], ProposalDraft.Status.FAILED)
        self.assertIn("iteration cap", result["error_message"])
        self.assertIn("3-iteration", result["error_message"])

    # -- a plain-text give-up gets its own distinct failure message -------

    def test_giveup_failure_records_distinct_message(self):
        # Arrange: one below-bar submit, then the model answers in plain text
        # (gives up) rather than submitting again.
        provider = _ScriptedProvider([_submit_turn(_clean_payload())])

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            panel=_FakePanel(overall=2),
            oa_client=_FakeOpenAlex(),
        )

        # Assert: distinct "ended without an accepted proposal" message (not an
        # iteration cap or plateau).
        self.assertEqual(result["status"], ProposalDraft.Status.FAILED)
        self.assertIn("ended without an accepted proposal", result["error_message"])
        self.assertNotIn("plateau", result["error_message"])
        self.assertEqual(Note.objects.count(), 0)

    # -- a provider that dies mid-run fails with the cause in the message --

    def test_provider_error_fails_with_cause_in_message(self):
        # Arrange: the provider dies on its first call (throttle, network, ...).
        class _ExplodingProvider(LLMProvider):
            def render_tools(self, _tools):
                return {"tools": []}

            def complete(self, **_kwargs):
                raise ValueError("throttled by bedrock")

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            provider=_ExplodingProvider(),
            panel=_FakePanel(overall=5),
            oa_client=_FakeOpenAlex(),
        )

        # Assert: FAILED (not stuck PROCESSING), with the provider detail --
        # not the "did not submit" give-up message.
        self.assertEqual(result["status"], ProposalDraft.Status.FAILED)
        self.assertIn("provider error", result["error_message"])
        self.assertIn("throttled by bedrock", result["error_message"])
        draft = ProposalDraft.objects.get(id=result["proposal_draft_id"])
        self.assertEqual(draft.status, ProposalDraft.Status.FAILED)

    # -- a truncated/filtered turn names its stop reason -------------------

    def test_incomplete_turn_failure_names_stop_reason(self):
        # Arrange: the model's only turn is text truncated by max_tokens --
        # neither an answer nor a tool call.
        provider = _ScriptedProvider(
            [
                AssistantTurn(
                    text_blocks=[TextBlock(text="partial draft...")],
                    tool_calls=[],
                    stop_reason=StopReason.MAX_TOKENS,
                )
            ]
        )

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            panel=_FakePanel(overall=5),
            oa_client=_FakeOpenAlex(),
        )

        # Assert: the actionable stop reason, not a generic provider error.
        self.assertEqual(result["status"], ProposalDraft.Status.FAILED)
        self.assertIn("max_tokens", result["error_message"])

    # -- an unexpected crash still lands the record in FAILED --------------

    def test_unexpected_crash_marks_failed_not_processing(self):
        # Arrange: a clean accepted submit, but the Note write blows up after
        # the loop -- the path that used to leave the draft stuck PROCESSING.
        provider = _ScriptedProvider([_submit_turn(_clean_payload())])

        # Act
        with patch(
            "research_ai.services.proposal_draft.runner.write_proposal_note",
            side_effect=RuntimeError("db connection lost"),
        ):
            result = run_proposal_draft(
                self.search_expert.id,
                provider=provider,
                panel=_FakePanel(overall=5),
                oa_client=_FakeOpenAlex(),
            )

        # Assert: FAILED with the unexpected error recorded, and the accepted
        # submission still persisted for inspection.
        self.assertEqual(result["status"], ProposalDraft.Status.FAILED)
        self.assertIn("unexpected error", result["error_message"])
        self.assertIn("db connection lost", result["error_message"])
        draft = ProposalDraft.objects.get(id=result["proposal_draft_id"])
        self.assertEqual(draft.status, ProposalDraft.Status.FAILED)
        self.assertEqual(
            draft.last_submission["sections"]["title"], "A Study of Folding"
        )

    # -- no grant to draft against fails fast, before any model call ------

    def test_missing_grant_fails_fast_without_model_calls(self):
        # Arrange: an expert search whose unified document carries no Grant.
        grantless_post = create_post(
            created_by=self.user,
            document_type=GRANT,
            renderable_text="A grant post with no Grant row attached.",
        )
        grantless_search = ExpertSearch.objects.create(
            created_by=self.user,
            unified_document=grantless_post.unified_document,
            query="protein folding",
        )
        search_expert = SearchExpert.objects.create(
            expert_search=grantless_search,
            expert=self.expert,
        )
        provider = _ScriptedProvider([_submit_turn(_clean_payload())])

        # Act
        result = run_proposal_draft(
            search_expert.id,
            provider=provider,
            panel=_FakePanel(overall=5),
            oa_client=_FakeOpenAlex(),
        )

        # Assert: failed naming the missing grant, and the model was never
        # called -- the run cannot succeed, so no tokens are spent.
        self.assertEqual(result["status"], ProposalDraft.Status.FAILED)
        self.assertIn("no grant", result["error_message"])
        self.assertEqual(provider.call_count, 0)

    # -- a crashed gate check ends the run naming the crash ---------------

    def test_gate_crash_fails_run_with_cause_not_iteration_cap(self):
        # Arrange: the panel (gate infrastructure) raises. Without containment
        # the crash would go back to the model as a retryable tool error and
        # the run would grind to a misleading iteration-cap failure.
        class _ExplodingPanel:
            model_ids = ["fake-judge"]

            def score(self, _proposal, *, context=None):
                raise ValueError("judge context exploded")

        provider = _AlwaysSubmitProvider(_clean_payload())

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            panel=_ExplodingPanel(),
            oa_client=_FakeOpenAlex(),
        )

        # Assert: terminal on the first crash with the real cause, and the
        # crashed round's submission is still persisted for inspection.
        self.assertEqual(result["status"], ProposalDraft.Status.FAILED)
        self.assertIn("gate check crashed", result["error_message"])
        self.assertIn("judge context exploded", result["error_message"])
        self.assertEqual(provider.call_count, 1)
        draft = ProposalDraft.objects.get(id=result["proposal_draft_id"])
        self.assertEqual(
            draft.last_submission["sections"]["title"], "A Study of Folding"
        )

    # -- an empty judge panel is an infrastructure failure, not a 1.0 ------

    def test_empty_judge_panel_fails_run_as_unavailable(self):
        # Arrange: the panel runs but no judge returns a score, so its rollup
        # carries only empty-input default 1s and judges_reporting=0.
        class _EmptyPanel:
            model_ids = ["fake-judge"]

            def score(self, _proposal, *, context=None):
                return {
                    "scores": dict.fromkeys(_CRITERIA, 1),
                    "overall": 1.0,
                    "gaps": [],
                    "judges_reporting": 0,
                    "judge_errors": ["fake-judge: turn ended max_tokens"],
                }

        provider = _AlwaysSubmitProvider(_clean_payload())

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            panel=_EmptyPanel(),
            oa_client=_FakeOpenAlex(),
        )

        # Assert: failed as "panel unavailable" after one round -- not scored
        # as 1.0 quality, not ground down to a plateau or round budget -- and
        # the recorded message names what the judges did.
        self.assertEqual(result["status"], ProposalDraft.Status.FAILED)
        self.assertIn("judge panel unavailable", result["error_message"])
        self.assertIn("turn ended max_tokens", result["error_message"])
        self.assertNotIn("plateau", result["error_message"])
        self.assertEqual(provider.call_count, 1)

    # -- a verified citation grounds even outside the researcher's works ---

    def test_verified_citation_grounds_outside_researcher_works(self):
        # Arrange: a field-level paper NOT in the researcher's works (so not in
        # provenance), but whose DOI resolves exact against OpenAlex ground truth.
        citations = [
            {
                "claim_id": "field1",
                "doi": "10.1/ext",
                "title": "Extracellular Matrix and Remyelination",
                "authors": ["Alan Turing"],
            }
        ]
        oa = _FakeOpenAlex(
            {
                "10.1/ext": {
                    "display_name": "Extracellular Matrix and Remyelination",
                    "publication_year": 2021,
                    "doi": "https://doi.org/10.1/ext",
                    "id": "https://openalex.org/W7",
                    "authorships": [{"author": {"display_name": "Alan Turing"}}],
                }
            }
        )
        provider = _ScriptedProvider([_submit_turn(_clean_payload(citations))])

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            panel=_FakePanel(overall=5),
            oa_client=oa,
        )

        # Assert: verify_citations grounds it, so the citation gate passes and the
        # run is accepted -- no re-fetch through the author tools required.
        self.assertEqual(result["status"], ProposalDraft.Status.COMPLETED)
        self.assertTrue(result["gate_report"]["citations"]["ok"])
        self.assertEqual(result["gate_report"]["citations"]["ungrounded"], [])

    # -- a minor_drift citation renders the resolved record, not the claim --

    def test_minor_drift_citation_is_corrected_in_rendered_references(self):
        # Arrange: the claimed title/authors drift from what the DOI resolves
        # to (same paper), so the verifier classifies it minor_drift and the
        # gate must adopt the resolved record before the References render.
        citations = [
            {
                "claim_id": "drift1",
                "doi": "10.1/drift",
                "title": "Extracellular Matrix and Remyelination",
                "authors": ["A. Turing"],
            }
        ]
        oa = _FakeOpenAlex(
            {
                "10.1/drift": {
                    "display_name": (
                        "The Extracellular Matrix and Remyelination in CNS Disease"
                    ),
                    "publication_year": 2021,
                    "doi": "https://doi.org/10.1/drift",
                    "id": "https://openalex.org/W7",
                    "authorships": [{"author": {"display_name": "Alan M. Turing"}}],
                }
            }
        )
        provider = _ScriptedProvider([_submit_turn(_clean_payload(citations))])

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            panel=_FakePanel(overall=5),
            oa_client=oa,
        )

        # Assert: accepted (minor_drift passes the gate), the correction is
        # reported, and the Note's References carry the resolved title/authors
        # instead of what the model typed.
        self.assertEqual(result["status"], ProposalDraft.Status.COMPLETED)
        self.assertEqual(result["gate_report"]["citations"]["corrected"], ["drift1"])
        note = Note.objects.get(id=result["note_id"])
        plain_text = note.latest_version.plain_text
        self.assertIn(
            "Alan M. Turing (2021). The Extracellular Matrix and Remyelination in "
            "CNS Disease. https://doi.org/10.1/drift",
            plain_text,
        )
        self.assertNotIn("A. Turing. Extracellular Matrix", plain_text)

    # -- an unretrieved, unverifiable citation is still ungrounded ---------

    def test_unverifiable_citation_is_ungrounded(self):
        # Arrange: a citation whose DOI does not resolve and is not in provenance.
        citations = [
            {"claim_id": "ghost", "doi": "10.1/missing", "title": "Ghost Paper"}
        ]
        provider = _ScriptedProvider([_submit_turn(_clean_payload(citations))])

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            panel=_FakePanel(overall=5),
            oa_client=_FakeOpenAlex(),
        )

        # Assert: unretrieved AND unverifiable => ungrounded, submit blocked.
        self.assertEqual(result["status"], ProposalDraft.Status.FAILED)
        report = result["gate_report"]
        self.assertFalse(report["citations"]["ok"])
        self.assertIn("ghost", report["citations"]["ungrounded"])

    # -- the agent is given no self-judge tool (submit is the only judge) --

    def test_agent_toolset_has_no_judge_tool(self):
        # Arrange
        draft = ProposalDraft.objects.create(
            search_expert=self.search_expert,
            status=ProposalDraft.Status.PENDING,
            step=ProposalDraft.Step.QUEUED,
        )
        runner = _ProposalDraftRunner(
            self.search_expert, draft, oa_client=_FakeOpenAlex()
        )

        # Act
        toolset = runner._compose_toolset(_ScriptedProvider([]))

        # Assert: no agent-facing judge; the panel scores every submit at the
        # gate. verify_citations (deterministic, cheap) is still available.
        self.assertNotIn("judge_proposal", toolset.names)
        self.assertIn("verify_citations", toolset.names)
        self.assertIn("submit_proposal", toolset.names)
        submit_tool = toolset.get("submit_proposal")
        sections_schema = submit_tool.input_schema["properties"]["sections"]
        self.assertIn("limitations", sections_schema["properties"])
        self.assertIn("limitations", sections_schema["required"])

    # -- the agent reads full text through the profile-scoped tool --------

    def test_agent_fulltext_tool_is_the_profile_scoped_one(self):
        # Arrange: the OpenAlex profile-builder toolset and the proposal
        # fulltext toolset both define a get_work_fulltext tool.
        draft = ProposalDraft.objects.create(
            search_expert=self.search_expert,
            status=ProposalDraft.Status.PENDING,
            step=ProposalDraft.Step.QUEUED,
        )
        runner = _ProposalDraftRunner(
            self.search_expert, draft, oa_client=_FakeOpenAlex()
        )

        # Act
        toolset = runner._compose_toolset(_ScriptedProvider([]))

        # Assert: the composed tool is the proposal one (profile-scoped,
        # fetch-capped), not the profile builder's OpenAlex reader.
        tool = toolset.get("get_work_fulltext")
        self.assertIsNotNone(tool)
        self.assertIs(tool.handler.__self__, runner.fulltext_toolset)

    # -- cancelling a run in flight ----------------------------------------

    def _pending_draft(self):
        return ProposalDraft.objects.create(
            search_expert=self.search_expert,
            created_by=self.user,
            status=ProposalDraft.Status.PENDING,
            step=ProposalDraft.Step.QUEUED,
        )

    def test_cancelling_mid_run_ends_cancelled_and_ships_no_note(self):
        # Arrange: a run whose only round clears every gate, cancelled while the
        # panel is judging it. The accepted round is exactly what makes this
        # worth checking -- the run has a shippable proposal in hand.
        draft = self._pending_draft()
        cancels = ProposalDraftCancelService()

        class _CancellingPanel(_FakePanel):
            def score(self, proposal, *, context=None):
                cancels.cancel(ProposalDraft.objects.get(id=draft.id))
                return super().score(proposal, context=context)

        provider = _ScriptedProvider([_submit_turn(_clean_payload())])

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            draft_id=draft.id,
            provider=provider,
            panel=_CancellingPanel(overall=5),
            oa_client=_FakeOpenAlex(),
        )

        # Assert: cancelled rather than completed, and no Note -- a run someone
        # called off must not still publish its proposal.
        self.assertEqual(result["status"], ProposalDraft.Status.CANCELLED)
        draft.refresh_from_db()
        self.assertEqual(draft.status, ProposalDraft.Status.CANCELLED)
        self.assertEqual(draft.error_message, "")
        self.assertIsNone(draft.note)
        self.assertEqual(Note.objects.count(), 0)
        # The work in hand is still persisted, as it is for a failed run.
        self.assertTrue(draft.last_submission)

    def test_a_cancelled_run_spends_no_further_judge_panels(self):
        # Arrange: an always-submitting provider would keep going for the whole
        # round budget. Cancel lands during the first round's judging, and the
        # score is below the bar, so the run would otherwise fail.
        draft = self._pending_draft()
        cancels = ProposalDraftCancelService()

        class _CancellingPanel(_FakePanel):
            def score(self, proposal, *, context=None):
                cancels.cancel(ProposalDraft.objects.get(id=draft.id))
                return super().score(proposal, context=context)

        panel = _CancellingPanel(overall=1, gaps=["raise overall quality"])
        provider = _AlwaysSubmitProvider(_clean_payload())

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            draft_id=draft.id,
            provider=provider,
            panel=panel,
            oa_client=_FakeOpenAlex(),
        )

        # Assert: the next round is cut before the gates run, so judging -- the
        # most expensive thing a round does -- happens once and not again. The
        # below-bar score never becomes a failure, either: cancellation reaches
        # the run as an ordinary error, and the guard keeps it out of FAILED.
        self.assertEqual(result["status"], ProposalDraft.Status.CANCELLED)
        self.assertEqual(len(panel.contexts), 1)
        draft.refresh_from_db()
        self.assertEqual(draft.status, ProposalDraft.Status.CANCELLED)
        self.assertEqual(draft.error_message, "")

    def test_a_run_with_no_agent_trace_still_stops_when_cancelled(self):
        # Arrange: the agent trace is best-effort -- a run whose execution could
        # not be created keeps drafting without one. Then the loop's own
        # ownership check has nothing to read, and the draft's status is the only
        # thing that can stop the run.
        draft = self._pending_draft()
        cancels = ProposalDraftCancelService()

        class _CancellingPanel(_FakePanel):
            def score(self, proposal, *, context=None):
                cancels.cancel(ProposalDraft.objects.get(id=draft.id))
                return super().score(proposal, context=context)

        panel = _CancellingPanel(overall=1, gaps=["raise overall quality"])
        provider = _AlwaysSubmitProvider(_clean_payload())
        broken_executions = Mock(wraps=AgentExecutionService())
        broken_executions.start.side_effect = RuntimeError("no trace today")

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            draft_id=draft.id,
            provider=provider,
            panel=panel,
            oa_client=_FakeOpenAlex(),
            execution_service=broken_executions,
        )

        # Assert
        self.assertEqual(result["status"], ProposalDraft.Status.CANCELLED)
        self.assertEqual(len(panel.contexts), 1)
        self.assertFalse(AgentExecution.objects.exists())

    def test_a_refused_completion_leaves_no_published_note_behind(self):
        # Arrange: the narrowest window there is -- every checkpoint has passed
        # and the run holds an accepted proposal, so the Note is written before
        # the status that would justify it. If the COMPLETED write is then
        # refused, the Note must not survive: reporting a draft cancelled while a
        # proposal goes out under the expert's name is the worst outcome here.
        #
        # The refusal is injected rather than raced, because a cancel issued from
        # this thread would join the run's own transaction and roll back with it.
        # Which statuses the guard refuses is covered directly in
        # ``test_proposal_draft_cancel``.
        draft = self._pending_draft()
        provider = _ScriptedProvider([_submit_turn(_clean_payload())])

        def _refuse(_self, _note):
            raise ProposalDraftCancelledError("cancelled before it shipped")

        # Act
        with patch.object(DraftRecorder, "complete", _refuse):
            result = run_proposal_draft(
                self.search_expert.id,
                draft_id=draft.id,
                provider=provider,
                panel=_FakePanel(overall=5),
                oa_client=_FakeOpenAlex(),
            )

        # Assert: the Note went with the rolled-back transaction, and nothing
        # points at one. The run did reach a terminal status -- which one depends
        # on why the write was refused, and is not what this pins.
        self.assertEqual(Note.objects.count(), 0)
        draft.refresh_from_db()
        self.assertIsNone(draft.note)
        self.assertNotEqual(result["status"], ProposalDraft.Status.COMPLETED)
        self.assertNotEqual(draft.status, ProposalDraft.Status.PROCESSING)

    def test_a_trace_created_as_the_draft_is_cancelled_is_not_left_running(self):
        # Arrange: the cancel lands after mark_processing and before the trace
        # exists, so it finds no execution to stop -- and then the run creates
        # one. Nothing sweeps for stalled executions any more, and retrying the
        # endpoint on an already-cancelled draft used to return before looking,
        # so an execution left RUNNING here would have stayed that way.
        draft = self._pending_draft()
        cancels = ProposalDraftCancelService()
        real_start = _ProposalDraftRunner._start_agent_recording

        def _cancel_then_start(self_runner, run_config):
            cancels.cancel(ProposalDraft.objects.get(id=draft.id))
            return real_start(self_runner, run_config)

        # Act
        with patch.object(
            _ProposalDraftRunner, "_start_agent_recording", _cancel_then_start
        ):
            result = run_proposal_draft(
                self.search_expert.id,
                draft_id=draft.id,
                provider=_AlwaysSubmitProvider(_clean_payload()),
                panel=_FakePanel(overall=5),
                oa_client=_FakeOpenAlex(),
            )

        # Assert: the draft is cancelled and its trace reached a terminal status
        # of its own, so the conversation is not left permanently busy.
        self.assertEqual(result["status"], ProposalDraft.Status.CANCELLED)
        self.assertTrue(AgentExecution.objects.exists())
        self.assertFalse(
            AgentExecution.objects.filter(
                status__in=[
                    AgentExecution.Status.RUNNING,
                    AgentExecution.Status.PENDING,
                ]
            ).exists()
        )

    def test_cancelling_between_the_claim_and_the_first_write_runs_nothing(self):
        # Arrange: the task claimed the draft, so it is PROCESSING, and the
        # cancel lands before the runner's own first write. That write used to be
        # an unguarded save that would have put PROCESSING straight back.
        draft = self._pending_draft()
        ProposalDraft.objects.filter(id=draft.id).update(
            status=ProposalDraft.Status.PROCESSING
        )
        cancels = ProposalDraftCancelService()
        provider = _AlwaysSubmitProvider(_clean_payload())
        panel = _FakePanel(overall=5)

        def _cancel_then_config(self_runner):
            cancels.cancel(ProposalDraft.objects.get(id=draft.id))
            return {"generator_model_id": "fake"}

        # Act
        with patch.object(_ProposalDraftRunner, "_run_config", _cancel_then_config):
            result = run_proposal_draft(
                self.search_expert.id,
                draft_id=draft.id,
                provider=provider,
                panel=panel,
                oa_client=_FakeOpenAlex(),
            )

        # Assert: no model was called and no judging was paid for.
        self.assertEqual(result["status"], ProposalDraft.Status.CANCELLED)
        draft.refresh_from_db()
        self.assertEqual(draft.status, ProposalDraft.Status.CANCELLED)
        self.assertEqual(provider.call_count, 0)
        self.assertEqual(len(panel.contexts), 0)
        self.assertEqual(Note.objects.count(), 0)
