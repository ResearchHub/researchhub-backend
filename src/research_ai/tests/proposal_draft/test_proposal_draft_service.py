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
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from note.models import Note
from purchase.models import Grant
from research_ai.models import Expert, ExpertSearch, ProposalDraft, SearchExpert
from research_ai.services.agent.types import (
    AssistantTurn,
    StopReason,
    TextBlock,
    ToolUseBlock,
)
from research_ai.services.proposal_draft import run_proposal_draft
from research_ai.services.proposal_draft.runner import _ProposalDraftRunner
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

    def __init__(self, overall=5, gaps=None):
        self.model_ids = ["fake-judge"]
        self._overall = overall
        self._gaps = gaps or []
        self.contexts = []

    def score(self, _proposal, *, context=None):
        self.contexts.append(context)
        return {
            "scores": dict.fromkeys(_CRITERIA, self._overall),
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


class _ScriptedProvider:
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


class _AlwaysSubmitProvider:
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


class _SequenceSubmitProvider:
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


def _prosemirror_doc():
    return {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 1},
                "content": [{"type": "text", "text": "A Study of Folding"}],
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Body text."}],
            },
        ],
    }


def _clean_payload(citations=None):
    return {
        "sections": {
            "title": "A Study of Folding",
            "hypothesis": "We hypothesize that X drives Y.",
            "approach": "We will measure X under Y conditions.",
            "why_this_team": "Jane Smith has published on protein folding.",
            "scope_timeline": "Over 24 months within the $50,000 budget.",
        },
        "prosemirror": _prosemirror_doc(),
        # Comfortably above the minimum word count.
        "plain_text": "alpha beta gamma delta epsilon " * 80,
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

        # Act
        result = run_proposal_draft(
            self.search_expert.id,
            provider=provider,
            panel=panel,
            oa_client=_FakeOpenAlex(),
        )

        # Assert: status, the Note + content, and the draft linkage.
        self.assertEqual(result["status"], ProposalDraft.Status.COMPLETED)
        note = Note.objects.get(id=result["note_id"])
        self.assertEqual(note.title, "A Study of Folding")
        self.assertIsNone(note.created_by)
        self.assertIsNone(note.organization)
        self.assertIsNotNone(note.latest_version)  # set by the post_save signal
        # json is stored as a JSON-encoded string (matching the view path and
        # what the editor's JSON.parse expects), not a raw object.
        self.assertIsInstance(note.latest_version.json, str)
        self.assertEqual(json.loads(note.latest_version.json), _prosemirror_doc())

        draft = ProposalDraft.objects.get(id=result["proposal_draft_id"])
        self.assertEqual(draft.note_id, note.id)
        self.assertEqual(draft.status, ProposalDraft.Status.COMPLETED)
        self.assertEqual(draft.step, ProposalDraft.Step.DONE)
        self.assertEqual(draft.final_scores["overall"], 5)
        self.assertEqual(draft.rounds_used, 1)
        self.assertTrue(panel.contexts)  # panel was scored at least once
        self.assertEqual(
            panel.contexts[0]["rfp"]["organization"],
            "National Science Foundation",
        )
        self.assertEqual(
            panel.contexts[0]["researcher_profile"]["works"][0]["source_url"],
            "https://doi.org/10.1/a",
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
        toolset = runner._compose_toolset()

        # Assert: the tool is exposed to the agent, and the injected client is
        # used, with its own provenance kept separate from citation grounding.
        self.assertIn("web_search", toolset.names)
        self.assertIs(runner.web_search_toolset._client, sentinel)
        self.assertIsNot(runner.web_search_toolset.provenance, runner.provenance)

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
        # Arrange: the score climbs 2 -> 3 -> 4 then flatlines. The early gains
        # reset the counter, so the run runs past round 4 and only plateaus once
        # the score has been flat for three rounds (rounds 4, 5, 6).
        provider = _AlwaysSubmitProvider(_clean_payload())
        panel = _SequencePanel([2, 3, 4])

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

    # -- a failed run persists the best draft, not the last ----------------

    @override_settings(
        RESEARCH_AI_PROPOSAL_MAX_ROUNDS=8,
        RESEARCH_AI_PROPOSAL_PLATEAU_PATIENCE=3,
    )
    def test_failed_run_persists_best_scoring_draft_not_last(self):
        # Arrange: round 1 scores the peak (4), then the score regresses to 3 and
        # flatlines, so the plateau guard stops the loop on a round whose draft is
        # worse than the peak. Each round submits a differently-titled payload so
        # the persisted draft is identifiable.
        peak = _clean_payload()
        peak["sections"]["title"] = "Peak Draft"
        regressed = _clean_payload()
        regressed["sections"]["title"] = "Regressed Draft"
        provider = _SequenceSubmitProvider([peak, regressed])
        panel = _SequencePanel([4, 3])

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
        self.assertEqual(draft.gate_report["panel"]["overall"], 4)
        self.assertEqual(draft.final_scores["overall"], 4)
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
        class _ExplodingProvider:
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
