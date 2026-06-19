"""Unit tests for the researcher-profile agent (orchestration + grounding)."""

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from research_ai.services.researcher_profile.agent import run_profile_agent
from research_ai.tests.researcher_profile.helpers import make_expert
from utils.openalex import Work
from utils.tests.openalex_helpers import create_oa_work


class ScriptedLLM:
    """Fake BedrockLLMService: replays a fixed sequence of tool calls.

    Each scripted ``(name, input)`` is run through the real toolset dispatch, so
    the agent's grounding and assembly are exercised end to end without Bedrock.
    """

    def __init__(self, calls):
        self.calls = calls

    def run_tool_loop(self, system_prompt, user_prompt, *, tools, dispatch, **kwargs):
        for name, tool_input in self.calls:
            _, stop = dispatch(name, tool_input)
            if stop:
                break
        return ""


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
        llm = ScriptedLLM(
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
        profile = run_profile_agent(make_expert(), llm=llm, oa_client=client)
        # Assert
        self.assertEqual(profile["schema_version"], 2)
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
        llm = ScriptedLLM(
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
        profile = run_profile_agent(make_expert(), llm=llm, oa_client=client)
        # Assert: only the grounded work survives; the drop is recorded.
        self.assertEqual([w["title"] for w in profile["works"]], ["Lead Paper"])
        self.assertTrue(any("ungrounded" in e for e in profile["errors"]))

    def test_blanks_ungrounded_pdf_url(self):
        # Arrange: real source_url, but a pdf_url the tools never returned.
        work = _work()
        client = _oa_client_returning(work)
        tampered = _as_submitted_work(work)
        tampered["pdf_url"] = "https://example.org/not-real.pdf"
        llm = ScriptedLLM(
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
        profile = run_profile_agent(make_expert(), llm=llm, oa_client=client)
        # Assert
        self.assertEqual(profile["works"][0]["pdf_url"], "")

    def test_caps_works_at_five(self):
        # Arrange: six grounded works submitted.
        works = [_work(title=f"Paper {i}", year=2020 + i) for i in range(6)]
        client = _oa_client_returning(*works)
        llm = ScriptedLLM(
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
        profile = run_profile_agent(make_expert(), llm=llm, oa_client=client)
        # Assert
        self.assertEqual(len(profile["works"]), 5)

    def test_unresolved_submission(self):
        # Arrange: the model gives up with a null author id.
        llm = ScriptedLLM(
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
        profile = run_profile_agent(make_expert(), llm=llm, oa_client=MagicMock())
        # Assert
        self.assertIsNone(profile["resolution"]["openalex_author_id"])
        self.assertEqual(profile["works"], [])

    def test_missing_submission_is_recorded(self):
        # Arrange: the loop ends without ever calling submit_profile.
        llm = ScriptedLLM([("get_author_works", {"openalex_author_id": "A123"})])
        client = _oa_client_returning(_work())
        # Act
        profile = run_profile_agent(make_expert(), llm=llm, oa_client=client)
        # Assert
        self.assertIsNone(profile["resolution"]["openalex_author_id"])
        self.assertTrue(any("did not submit" in e for e in profile["errors"]))

    def test_agent_failure_is_recorded_not_raised(self):
        # Arrange: the LLM blows up mid-run.
        llm = MagicMock()
        llm.run_tool_loop.side_effect = RuntimeError("bedrock exploded")
        # Act
        profile = run_profile_agent(make_expert(), llm=llm, oa_client=MagicMock())
        # Assert
        self.assertTrue(any("bedrock exploded" in e for e in profile["errors"]))
        self.assertEqual(profile["works"], [])
