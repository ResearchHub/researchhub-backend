"""Unit tests for the multi-model proposal judge panel (no network, no LLM)."""

import json

from django.test import SimpleTestCase

from research_ai.services.agent.types import AssistantTurn, StopReason, TextBlock
from research_ai.services.proposal_draft.judge_panel import (
    JUDGE_MAX_TOKENS,
    ProposalJudgePanel,
)

_PANEL_LOGGER = "research_ai.services.proposal_draft.judge_panel"


def _as_text(payload) -> str:
    return payload if isinstance(payload, str) else json.dumps(payload)


class _FakeProvider:
    """A judge provider whose ``complete`` returns a fixed JSON text."""

    def __init__(self, model_id, payload, stop_reason=StopReason.END_TURN):
        self.model_id = model_id
        self._text = _as_text(payload)
        self._stop_reason = stop_reason
        self.calls = []

    def complete(self, **_kwargs) -> AssistantTurn:
        self.calls.append(_kwargs)
        return AssistantTurn(
            text_blocks=[TextBlock(text=self._text)],
            tool_calls=[],
            stop_reason=self._stop_reason,
        )


class _FlakyProvider:
    """A judge provider that returns each payload in turn, one per call."""

    def __init__(self, model_id, payloads):
        self.model_id = model_id
        self._texts = [_as_text(p) for p in payloads]
        self.calls = []

    def complete(self, **_kwargs) -> AssistantTurn:
        self.calls.append(_kwargs)
        text = self._texts[min(len(self.calls) - 1, len(self._texts) - 1)]
        return AssistantTurn(
            text_blocks=[TextBlock(text=text)],
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
        self.assertEqual(result["overall"], 3.29)  # mean of [3,4,3,4,3,3,3]
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

        # Assert: degraded to the one parseable judge, and the rollup says so.
        self.assertEqual(
            result["scores"],
            {"c1": 2, "c2": 2, "c3": 2, "c4": 2, "c5": 2, "c6": 2, "c7": 2},
        )
        self.assertEqual(result["judges_reporting"], 1)

    def test_score_with_no_reporting_judges_says_so(self):
        # Arrange: every judge fails to produce parseable JSON.
        providers = [
            _FakeProvider("j1", "not json at all"),
            _FakeProvider("j2", "also not json"),
        ]
        panel = ProposalJudgePanel(providers=providers)

        # Act
        result = panel.score("draft")

        # Assert: the default 1s are flagged as no verdict at all, so callers
        # can tell an infrastructure failure from a low score, and each judge's
        # reason rides along with the rollup.
        self.assertEqual(result["judges_reporting"], 0)
        self.assertEqual(result["overall"], 1.0)
        self.assertEqual(len(result["judge_errors"]), 2)
        self.assertTrue(result["judge_errors"][0].startswith("j1: "))

    def test_score_retries_a_judge_that_fails_once(self):
        # Arrange: the judge's first call is unparseable, its second is a
        # verdict -- a single-judge panel must not die on one bad draw.
        provider = _FlakyProvider(
            "j1", ["not json at all", _build_scores(4, 4, 4, 4, 4, 4, c7=4)]
        )
        panel = ProposalJudgePanel(providers=[provider])

        # Act
        result = panel.score("draft")

        # Assert
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(result["judges_reporting"], 1)
        self.assertEqual(result["overall"], 4.0)
        self.assertEqual(result["judge_errors"], [])

    def test_score_rejects_a_truncated_judge_turn(self):
        # Arrange: the turn carries parseable JSON but ended at the token
        # ceiling, so what it holds is not a complete verdict.
        provider = _FakeProvider(
            "j1",
            _build_scores(5, 5, 5, 5, 5, 5, c7=5),
            stop_reason=StopReason.MAX_TOKENS,
        )
        panel = ProposalJudgePanel(providers=[provider])

        # Act
        result = panel.score("draft")

        # Assert: not scored, retried, and the reason names the truncation.
        self.assertEqual(result["judges_reporting"], 0)
        self.assertEqual(len(provider.calls), 2)
        self.assertIn("max_tokens", result["judge_errors"][0])

    def test_score_rejects_an_empty_judge_turn(self):
        # Arrange: a turn that emitted no text at all (all reasoning, no answer).
        provider = _FakeProvider("j1", "")
        panel = ProposalJudgePanel(providers=[provider])

        # Act
        result = panel.score("draft")

        # Assert
        self.assertEqual(result["judges_reporting"], 0)
        self.assertIn("no text", result["judge_errors"][0])

    def test_score_reports_a_judge_that_returns_the_wrong_json_shape(self):
        # Arrange: valid JSON, but an array where a verdict object belongs.
        provider = _FakeProvider("j1", "[1, 2, 3]")
        panel = ProposalJudgePanel(providers=[provider])

        # Act
        result = panel.score("draft")

        # Assert: skipped like any other failure, but not silently.
        self.assertEqual(result["judges_reporting"], 0)
        self.assertIn("not an object", result["judge_errors"][0])

    def test_score_sends_a_budget_that_covers_reasoning(self):
        # Arrange: thinking counts against max_tokens, so the default budget is
        # sized past the verdict itself.
        provider = _FakeProvider("j1", _build_scores(4, 4, 4, 4, 4, 4, c7=4))
        panel = ProposalJudgePanel(providers=[provider])

        # Act
        panel.score("draft")

        # Assert
        self.assertEqual(provider.calls[0]["max_tokens"], JUDGE_MAX_TOKENS)
        self.assertGreaterEqual(JUDGE_MAX_TOKENS, 32768)

    def test_score_logs_the_answer_that_would_not_parse(self):
        # Arrange: the reason alone cannot tell an empty or cut-off answer apart
        # from a malformed one, so the answer itself has to reach the log.
        answer = "I would rather explain my scores in prose."
        panel = ProposalJudgePanel(providers=[_FakeProvider("j1", answer)])

        # Act
        with self.assertLogs(_PANEL_LOGGER, level="WARNING") as logs:
            panel.score("draft")

        # Assert
        self.assertIn(answer, logs.output[0])
        self.assertIn(f"({len(answer)} chars)", logs.output[0])

    def test_score_logs_the_partial_text_of_a_truncated_answer(self):
        # Arrange: a verdict cut off at the token ceiling. Rejecting it for how
        # it ended must not cost the text it did emit -- that partial text is
        # what says whether the judge was writing JSON or still deliberating.
        answer = '{"scores": {"c1": 4, "c2"'
        panel = ProposalJudgePanel(
            providers=[_FakeProvider("j1", answer, stop_reason=StopReason.MAX_TOKENS)]
        )

        # Act
        with self.assertLogs(_PANEL_LOGGER, level="WARNING") as logs:
            panel.score("draft")

        # Assert
        self.assertIn(answer, logs.output[0])
        self.assertIn(f"({len(answer)} chars)", logs.output[0])

    def test_score_elides_the_middle_of_a_long_unusable_answer(self):
        # Arrange: a verdict's bulk is its middle; both ends are the diagnostic
        # part, and the whole thing must not land in the log.
        answer = f"{'head' * 200}{'tail' * 200}"
        panel = ProposalJudgePanel(providers=[_FakeProvider("j1", answer)])

        # Act
        with self.assertLogs(_PANEL_LOGGER, level="WARNING") as logs:
            panel.score("draft")

        # Assert: reported in full, logged in part.
        self.assertIn(f"({len(answer)} chars)", logs.output[0])
        self.assertIn("chars...]", logs.output[0])
        self.assertNotIn(answer, logs.output[0])

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
