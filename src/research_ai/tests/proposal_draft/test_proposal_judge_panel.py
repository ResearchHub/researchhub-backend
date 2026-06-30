"""Unit tests for the multi-model proposal judge panel (no network, no LLM)."""

import json

from django.test import SimpleTestCase

from research_ai.services.agent.types import AssistantTurn, StopReason, TextBlock
from research_ai.services.proposal_judge_panel import ProposalJudgePanel
from research_ai.services.proposal_tools.judge_tools import build_judge_tool


class _FakeProvider:
    """A judge provider whose ``complete`` returns a fixed JSON text."""

    def __init__(self, model_id, payload):
        self.model_id = model_id
        self._text = payload if isinstance(payload, str) else json.dumps(payload)
        self.calls = []

    def complete(self, **_kwargs) -> AssistantTurn:
        self.calls.append(_kwargs)
        return AssistantTurn(
            text_blocks=[TextBlock(text=self._text)],
            tool_calls=[],
            stop_reason=StopReason.END_TURN,
        )


def _build_scores(c1, c2, c3, c4, c5, c6, c7, gaps=None):
    return {
        "scores": {
            "c1": c1,
            "c2": c2,
            "c3": c3,
            "c4": c4,
            "c5": c5,
            "c6": c6,
            "c7": c7,
        },
        "gaps": gaps or [],
    }


class ProposalJudgePanelTests(SimpleTestCase):
    def _first_user_text(self, provider) -> str:
        """The first judge call's user-message text, with clear assertions.

        Guards each index so a missing call / message / block fails as a
        readable assertion instead of an opaque ``IndexError``.
        """
        self.assertTrue(provider.calls, "provider was never called")
        messages = provider.calls[0]["messages"]
        self.assertTrue(messages, "judge call had no messages")
        content = messages[0].content
        self.assertTrue(content, "user message had no content blocks")
        return content[0].text

    def test_score_reduces_each_criterion_by_median(self):
        # Arrange: three judges; per-criterion median is the reduction.
        providers = [
            _FakeProvider(
                "j1", _build_scores(5, 4, 3, 2, 1, 5, c7=5, gaps=["tighten scope"])
            ),
            _FakeProvider(
                "j2", _build_scores(3, 4, 3, 4, 3, 1, c7=1, gaps=["cite a source"])
            ),
            _FakeProvider(
                "j3", _build_scores(1, 4, 5, 4, 5, 3, c7=3, gaps=["tighten scope"])
            ),
        ]
        panel = ProposalJudgePanel(providers=providers)

        # Act
        result = panel.score("a draft proposal")

        # Assert: median per criterion across the three judges.
        self.assertEqual(
            result["scores"],
            {"c1": 3, "c2": 4, "c3": 3, "c4": 4, "c5": 3, "c6": 3, "c7": 3},
        )
        self.assertEqual(result["overall"], 3)  # median of [3,4,3,4,3,3,3]
        self.assertEqual(result["gaps"], ["tighten scope", "cite a source"])

    def test_score_coerces_and_clamps_out_of_range_values(self):
        # Arrange: a lone judge emits junk / out-of-range values (median == value).
        providers = [_FakeProvider("j1", _build_scores(9, 0, "x", None, 4, 3, c7=3))]
        panel = ProposalJudgePanel(providers=providers)

        # Act
        result = panel.score("draft")

        # Assert: 9->5, 0->1, "x"->1, None->1; valid values pass through.
        self.assertEqual(
            result["scores"],
            {"c1": 5, "c2": 1, "c3": 1, "c4": 1, "c5": 4, "c6": 3, "c7": 3},
        )

    def test_score_skips_unparseable_judge(self):
        # Arrange: one judge returns non-JSON; the panel degrades to the rest.
        providers = [
            _FakeProvider("j1", "not json at all"),
            _FakeProvider("j2", _build_scores(2, 2, 2, 2, 2, 2, c7=2)),
        ]
        panel = ProposalJudgePanel(providers=providers)

        # Act
        result = panel.score("draft")

        # Assert
        self.assertEqual(
            result["scores"],
            {"c1": 2, "c2": 2, "c3": 2, "c4": 2, "c5": 2, "c6": 2, "c7": 2},
        )

    def test_score_includes_evaluation_context(self):
        # Arrange
        provider = _FakeProvider("j1", _build_scores(4, 4, 4, 4, 4, 4, c7=4))
        panel = ProposalJudgePanel(providers=[provider])

        # Act
        panel.score(
            "draft",
            context={
                "rfp": {"amount": "50000.00", "currency": "USD"},
                "researcher_profile": {"works": [{"title": "Grounded Work"}]},
            },
        )

        # Assert
        user_text = self._first_user_text(provider)
        self.assertIn("## Evaluation context", user_text)
        self.assertIn("50000.00", user_text)
        self.assertIn("Grounded Work", user_text)

    def test_pairwise_majority_wins(self):
        # Arrange: A wins 2 of 3.
        providers = [
            _FakeProvider("j1", {"winner": "A"}),
            _FakeProvider("j2", {"winner": "B"}),
            _FakeProvider("j3", {"winner": "A"}),
        ]
        panel = ProposalJudgePanel(providers=providers)

        # Act / Assert
        self.assertEqual(panel.pairwise("draft a", "draft b"), "A")

    def test_pairwise_tie_breaks_to_a(self):
        # Arrange: 1-1 tie.
        providers = [
            _FakeProvider("j1", {"winner": "A"}),
            _FakeProvider("j2", {"winner": "B"}),
        ]
        panel = ProposalJudgePanel(providers=providers)

        # Act / Assert
        self.assertEqual(panel.pairwise("draft a", "draft b"), "A")

    def test_default_roster_is_single_generator_judge(self):
        # Arrange / Act: default roster from settings (no clients built).
        panel = ProposalJudgePanel(generator_model_id="us.anthropic.claude-opus-4-8")

        # Assert: the judge defaults to the generator model itself.
        self.assertEqual(panel.model_ids, ["us.anthropic.claude-opus-4-8"])

    def test_judge_tool_score_mode(self):
        # Arrange
        providers = [_FakeProvider("j1", _build_scores(4, 4, 4, 4, 4, 4, c7=4))]
        tool = build_judge_tool(ProposalJudgePanel(providers=providers))

        # Act
        result = tool.handler({"proposal": "draft", "mode": "score"})

        # Assert
        self.assertEqual(result["overall"], 4)
        self.assertFalse(tool.is_terminal)

    def test_judge_tool_pairwise_mode(self):
        # Arrange
        providers = [_FakeProvider("j1", {"winner": "B"})]
        tool = build_judge_tool(ProposalJudgePanel(providers=providers))

        # Act
        result = tool.handler({"proposal": "a", "mode": "pairwise", "candidate_b": "b"})

        # Assert
        self.assertEqual(result["winner"], "B")

    def test_judge_tool_pairwise_requires_candidate_b(self):
        # Arrange
        providers = [_FakeProvider("j1", {"winner": "A"})]
        tool = build_judge_tool(ProposalJudgePanel(providers=providers))

        # Act
        result = tool.handler({"proposal": "a", "mode": "pairwise"})

        # Assert
        self.assertIn("error", result)

    def test_judge_tool_uses_context_provider(self):
        # Arrange
        provider = _FakeProvider("j1", _build_scores(4, 4, 4, 4, 4, 4, c7=4))
        tool = build_judge_tool(
            ProposalJudgePanel(providers=[provider]),
            context_provider=lambda _args: {"rfp": {"short_title": "Focused RFP"}},
        )

        # Act
        result = tool.handler({"proposal": "draft", "mode": "score"})

        # Assert
        self.assertEqual(result["overall"], 4)
        user_text = self._first_user_text(provider)
        self.assertIn("Focused RFP", user_text)
