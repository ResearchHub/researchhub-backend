"""Unit tests for the researcher-profile agent (orchestration + grounding).

The agent runs on the core ``Agent`` loop. A ``FakeProvider`` replays a fixed
sequence of tool-call turns through the real ``OpenAlexToolset``, so the agent's
grounding and assembly are exercised end to end without Bedrock or the network.
"""

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from research_ai.services.agent.providers.base import LLMProvider
from research_ai.services.agent.types import (
    AssistantTurn,
    StopReason,
    TextBlock,
    ToolUseBlock,
)
from research_ai.services.researcher_profile.agent import run_profile_agent
from research_ai.tests.researcher_profile.helpers import make_expert
from utils.openalex import Work
from utils.tests.openalex_helpers import create_oa_work


def _tool_turn(index, name, tool_input):
    """A turn that requests a single tool call."""
    return AssistantTurn(
        text_blocks=[],
        tool_calls=[ToolUseBlock(id=f"t{index}", name=name, input=tool_input)],
        stop_reason=StopReason.TOOL_USE,
    )


def _text_turn(text):
    """A plain-text end-of-turn (the model finishing without a tool call)."""
    return AssistantTurn(
        text_blocks=[TextBlock(text=text)],
        tool_calls=[],
        stop_reason=StopReason.END_TURN,
    )


class FakeProvider(LLMProvider):
    """Replays a fixed queue of ``AssistantTurn``s; never touches the network."""

    def __init__(self, turns):
        self._turns = list(turns)

    def render_tools(self, tools):
        return {"tools": [tool.name for tool in tools]}

    def complete(self, *, system_prompt, messages, rendered_tools, **kwargs):
        return self._turns.pop(0)


def _scripted_provider(calls, *, final_text=None):
    """Build a provider that issues ``calls`` as tool turns, then optional text.

    A script ending in a terminal tool (``submit_profile``) needs no trailing
    text turn -- the loop stops once that tool runs.
    """
    turns = [_tool_turn(i, name, inp) for i, (name, inp) in enumerate(calls)]
    if final_text is not None:
        turns.append(_text_turn(final_text))
    return FakeProvider(turns)


def _oa_client_returning(*works):
    client = MagicMock()
    client.get_works_typed.return_value = list(works)
    return client


def _work(title="Lead Paper", year=2024, position="first"):
    return Work.from_openalex(create_oa_work(title, year, position), author_id=None)


def _as_submitted_work(work: Work) -> dict:
    return work.as_dict()


class RunProfileAgentTests(SimpleTestCase):
    def test_builds_profile_from_grounded_works(self):
        # Arrange: the model lists works, then submits one copied verbatim.
        work = _work()
        client = _oa_client_returning(work)
        provider = _scripted_provider(
            [
                (
                    "get_author_works",
                    {"openalex_author_id": "https://openalex.org/A123"},
                ),
                (
                    "submit_profile",
                    {
                        "resolution": {
                            "openalex_author_id": "https://openalex.org/A123",
                            "display_name": "Jane Doe",
                            "confidence": 0.95,
                            "reasoning": "ORCID match.",
                        },
                        "works": [_as_submitted_work(work)],
                    },
                ),
            ]
        )
        # Act
        profile = run_profile_agent(make_expert(), provider=provider, oa_client=client)
        # Assert
        self.assertEqual(profile["schema_version"], 1)
        self.assertEqual(
            profile["resolution"]["openalex_author_id"], "https://openalex.org/A123"
        )
        self.assertEqual(profile["resolution"]["confidence"], 0.95)
        self.assertEqual(len(profile["works"]), 1)
        self.assertEqual(
            profile["works"][0]["pdf_url"], "https://example.org/lead-paper.pdf"
        )
        self.assertEqual(profile["errors"], [])

    def test_drops_ungrounded_work(self):
        # Arrange: the model submits a work the tools never returned.
        work = _work()
        client = _oa_client_returning(work)
        fabricated = {
            "title": "Fabricated Paper",
            "source_url": "https://doi.org/10.1/made-up",
            "pdf_url": "https://example.org/made-up.pdf",
        }
        provider = _scripted_provider(
            [
                ("get_author_works", {"openalex_author_id": "A123"}),
                (
                    "submit_profile",
                    {
                        "resolution": {"openalex_author_id": "A123", "confidence": 0.9},
                        "works": [_as_submitted_work(work), fabricated],
                    },
                ),
            ]
        )
        # Act
        profile = run_profile_agent(make_expert(), provider=provider, oa_client=client)
        # Assert: only the grounded work survives; the drop is recorded.
        self.assertEqual([w["title"] for w in profile["works"]], ["Lead Paper"])
        self.assertTrue(any("ungrounded" in e for e in profile["errors"]))

    def test_blanks_ungrounded_pdf_url(self):
        # Arrange: real source_url, but a pdf_url the tools never returned.
        work = _work()
        client = _oa_client_returning(work)
        tampered = _as_submitted_work(work)
        tampered["pdf_url"] = "https://example.org/not-real.pdf"
        provider = _scripted_provider(
            [
                ("get_author_works", {"openalex_author_id": "A123"}),
                (
                    "submit_profile",
                    {
                        "resolution": {"openalex_author_id": "A123", "confidence": 0.9},
                        "works": [tampered],
                    },
                ),
            ]
        )
        # Act
        profile = run_profile_agent(make_expert(), provider=provider, oa_client=client)
        # Assert
        self.assertEqual(profile["works"][0]["pdf_url"], "")

    def test_caps_works_at_five(self):
        # Arrange: six grounded works submitted.
        works = [_work(title=f"Paper {i}", year=2020 + i) for i in range(6)]
        client = _oa_client_returning(*works)
        provider = _scripted_provider(
            [
                ("get_author_works", {"openalex_author_id": "A123"}),
                (
                    "submit_profile",
                    {
                        "resolution": {"openalex_author_id": "A123", "confidence": 0.9},
                        "works": [_as_submitted_work(w) for w in works],
                    },
                ),
            ]
        )
        # Act
        profile = run_profile_agent(make_expert(), provider=provider, oa_client=client)
        # Assert
        self.assertEqual(len(profile["works"]), 5)

    def test_unresolved_submission(self):
        # Arrange: the model gives up with a null author id.
        provider = _scripted_provider(
            [
                (
                    "submit_profile",
                    {
                        "resolution": {
                            "openalex_author_id": None,
                            "confidence": 0.1,
                            "reasoning": "No confident match.",
                        },
                        "works": [],
                    },
                ),
            ]
        )
        # Act
        profile = run_profile_agent(
            make_expert(), provider=provider, oa_client=MagicMock()
        )
        # Assert
        self.assertIsNone(profile["resolution"]["openalex_author_id"])
        self.assertEqual(profile["works"], [])

    def test_missing_submission_is_recorded(self):
        # Arrange: the loop ends in plain text without ever calling submit_profile.
        provider = _scripted_provider(
            [("get_author_works", {"openalex_author_id": "A123"})],
            final_text="No confident match; stopping.",
        )
        client = _oa_client_returning(_work())
        # Act
        profile = run_profile_agent(make_expert(), provider=provider, oa_client=client)
        # Assert
        self.assertIsNone(profile["resolution"]["openalex_author_id"])
        self.assertTrue(any("did not submit" in e for e in profile["errors"]))

    def test_agent_failure_is_recorded_not_raised(self):
        # Arrange: the provider blows up mid-run.
        provider = MagicMock()
        provider.complete.side_effect = RuntimeError("bedrock exploded")
        # Act
        profile = run_profile_agent(
            make_expert(), provider=provider, oa_client=MagicMock()
        )
        # Assert
        self.assertTrue(any("bedrock exploded" in e for e in profile["errors"]))
        self.assertEqual(profile["works"], [])
