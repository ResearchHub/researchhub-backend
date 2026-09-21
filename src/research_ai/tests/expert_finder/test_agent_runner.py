"""Key-path tests for the expert-finder agent runner.

Covers the critical success and failure flows: tool composition, grounded
submit, OpenAlex/email gates, and Brave web search. Edge cases live elsewhere.
"""

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from research_ai.constants import ExpertiseLevel, Region
from research_ai.services.agent.providers.base import LLMProvider
from research_ai.services.agent.types import (
    AssistantTurn,
    StopReason,
    TextBlock,
    ToolUseBlock,
)
from research_ai.services.expert_finder.agent_runner import (
    SUBMIT_EXPERTS,
    ExpertFinderAgentToolset,
    ground_submitted_experts,
    run_expert_finder_agent,
)
from research_ai.services.expert_finder.email_validation import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    EmailValidationService,
)
from research_ai.services.expert_finder.openalex_tools import (
    ExpertFinderOpenAlexToolset,
)
from research_ai.services.expert_finder.web_search_tools import (
    WEB_SEARCH,
    ExpertFinderWebSearchToolset,
)


def _tool_turn(index, name, tool_input):
    return AssistantTurn(
        text_blocks=[],
        tool_calls=[ToolUseBlock(id=f"t{index}", name=name, input=tool_input)],
        stop_reason=StopReason.TOOL_USE,
    )


def _text_turn(text):
    return AssistantTurn(
        text_blocks=[TextBlock(text=text)],
        tool_calls=[],
        stop_reason=StopReason.END_TURN,
    )


class FakeProvider(LLMProvider):
    def __init__(self, turns):
        self._turns = list(turns)

    def render_tools(self, tools):
        return {"tools": [tool.name for tool in tools]}

    def complete(self, *, system_prompt, messages, rendered_tools, **kwargs):
        return self._turns.pop(0)


def _scripted_provider(calls, *, final_text=None):
    turns = [_tool_turn(i, name, inp) for i, (name, inp) in enumerate(calls)]
    if final_text is not None:
        turns.append(_text_turn(final_text))
    return FakeProvider(turns)


def _insights(*, mailbox_exists=CONFIDENCE_HIGH):
    return {
        "MailboxValidation": {
            "IsValid": {"ConfidenceVerdict": CONFIDENCE_HIGH},
            "Evaluations": {
                "HasValidSyntax": {"ConfidenceVerdict": CONFIDENCE_HIGH},
                "HasValidDnsRecords": {"ConfidenceVerdict": CONFIDENCE_HIGH},
                "MailboxExists": {"ConfidenceVerdict": mailbox_exists},
                "IsDisposable": {"ConfidenceVerdict": CONFIDENCE_LOW},
                "IsRoleAddress": {"ConfidenceVerdict": CONFIDENCE_LOW},
                "IsRandomInput": {"ConfidenceVerdict": CONFIDENCE_LOW},
            },
        }
    }


def _expert_row(*, author_id="https://openalex.org/A999", email="ada@mit.edu"):
    return {
        "openalex_author_id": author_id,
        "first_name": "Ada",
        "last_name": "Expert",
        "email": email,
        "affiliation": "MIT",
        "expertise": "CRISPR",
        "notes": "Relevant recent work.",
        "sources": [{"text": "Faculty page", "url": "https://mit.edu/ada"}],
    }


class ToolCompositionTests(SimpleTestCase):
    def test_composes_discovery_contact_and_terminal_submit(self):
        # Arrange / Act
        tools = ExpertFinderAgentToolset().build_tools()
        names = {tool.name for tool in tools}
        terminal = {tool.name for tool in tools if tool.is_terminal}
        # Assert
        self.assertTrue(
            {
                "search_works",
                "get_author",
                WEB_SEARCH,
                "email_validate",
                SUBMIT_EXPERTS,
            }.issubset(names)
        )
        self.assertEqual(terminal, {SUBMIT_EXPERTS})


class GroundSubmittedExpertsTests(SimpleTestCase):
    def setUp(self):
        self.oa = ExpertFinderOpenAlexToolset(client=MagicMock())
        self.oa.returned_author_ids.add("a999")
        self.ses = MagicMock()
        self.ses.get_email_address_insights.return_value = _insights()
        self.email = EmailValidationService(client=self.ses)

    def test_keeps_grounded_validated_expert(self):
        # Arrange / Act
        kept, errors = ground_submitted_experts(
            [_expert_row()],
            openalex_toolset=self.oa,
            email_validation=self.email,
            expert_count=5,
        )
        # Assert
        self.assertEqual(errors, [])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["email"], "ada@mit.edu")
        self.assertEqual(
            kept[0]["sources"][0],
            {"text": "OpenAlex", "url": "https://openalex.org/A999"},
        )

    def test_drops_ungrounded_openalex_id(self):
        # Arrange / Act
        kept, errors = ground_submitted_experts(
            [_expert_row(author_id="https://openalex.org/A000")],
            openalex_toolset=self.oa,
            email_validation=self.email,
            expert_count=5,
        )
        # Assert
        self.assertEqual(kept, [])
        self.assertTrue(any("ungrounded" in e for e in errors))
        self.ses.get_email_address_insights.assert_not_called()

    def test_drops_invalid_email(self):
        # Arrange
        self.ses.get_email_address_insights.return_value = _insights(
            mailbox_exists=CONFIDENCE_LOW
        )
        # Act
        kept, errors = ground_submitted_experts(
            [_expert_row()],
            openalex_toolset=self.oa,
            email_validation=self.email,
            expert_count=5,
        )
        # Assert
        self.assertEqual(kept, [])
        self.assertTrue(errors)

    def test_drops_outside_region(self):
        # Arrange
        self.oa.returned_author_records["a999"] = {
            "id": "https://openalex.org/A999",
            "last_known_institutions": [{"display_name": "MPI", "country_code": "DE"}],
        }
        # Act
        kept, errors = ground_submitted_experts(
            [_expert_row()],
            openalex_toolset=self.oa,
            email_validation=self.email,
            expert_count=5,
            region_filter=Region.US,
        )
        # Assert
        self.assertEqual(kept, [])
        self.assertTrue(any("outside region" in e for e in errors))
        self.ses.get_email_address_insights.assert_not_called()

    def test_keeps_in_region_author(self):
        # Arrange
        self.oa.returned_author_records["a999"] = {
            "id": "https://openalex.org/A999",
            "last_known_institutions": [{"display_name": "MIT", "country_code": "US"}],
        }
        # Act
        kept, errors = ground_submitted_experts(
            [_expert_row()],
            openalex_toolset=self.oa,
            email_validation=self.email,
            expert_count=5,
            region_filter=Region.US,
        )
        # Assert
        self.assertEqual(errors, [])
        self.assertEqual(len(kept), 1)


class RunExpertFinderAgentTests(SimpleTestCase):
    def setUp(self):
        self.ses = MagicMock()
        self.ses.get_email_address_insights.return_value = _insights()
        self.email = EmailValidationService(client=self.ses)
        self.oa_client = MagicMock()
        self.oa_client.get_author.return_value = {
            "id": "https://openalex.org/A999",
            "display_name": "Ada Expert",
            "orcid": None,
            "works_count": 40,
            "cited_by_count": 100,
            "summary_stats": {},
            "last_known_institutions": [{"display_name": "MIT", "country_code": "US"}],
            "affiliations": [],
            "topics": [],
        }

    def test_happy_path_returns_grounded_experts(self):
        # Arrange
        provider = _scripted_provider(
            [
                (
                    "get_author",
                    {"openalex_author_id": "https://openalex.org/A999"},
                ),
                ("submit_experts", {"experts": [_expert_row()]}),
            ]
        )
        # Act
        result = run_expert_finder_agent(
            query="CRISPR therapeutics for rare disease",
            expert_count=5,
            expertise_level=ExpertiseLevel.MID_CAREER,
            region_filter=Region.US,
            provider=provider,
            oa_client=self.oa_client,
            email_validation=self.email,
        )
        # Assert
        self.assertEqual(len(result["experts"]), 1)
        self.assertEqual(result["experts"][0]["email"], "ada@mit.edu")
        self.assertEqual(result["errors"], [])

    def test_no_submit_returns_empty(self):
        # Arrange
        provider = _scripted_provider([], final_text="I give up.")
        # Act
        result = run_expert_finder_agent(
            query="Something",
            expert_count=3,
            expertise_level=ExpertiseLevel.ALL_LEVELS,
            region_filter=Region.ALL_REGIONS,
            provider=provider,
            oa_client=self.oa_client,
            email_validation=self.email,
        )
        # Assert
        self.assertEqual(result["experts"], [])
        self.assertTrue(any("did not submit" in e for e in result["errors"]))

    def test_hard_drops_out_of_region_on_submit(self):
        # Arrange: author is US-affiliated but search asked for Europe.
        provider = _scripted_provider(
            [
                (
                    "get_author",
                    {"openalex_author_id": "https://openalex.org/A999"},
                ),
                ("submit_experts", {"experts": [_expert_row()]}),
            ]
        )
        # Act
        result = run_expert_finder_agent(
            query="CRISPR therapeutics",
            expert_count=5,
            expertise_level=ExpertiseLevel.MID_CAREER,
            region_filter=Region.EUROPE,
            provider=provider,
            oa_client=self.oa_client,
            email_validation=self.email,
        )
        # Assert
        self.assertEqual(result["experts"], [])
        self.assertTrue(any("outside region" in e for e in result["errors"]))


class WebSearchToolTests(SimpleTestCase):
    def test_returns_results_when_configured(self):
        # Arrange
        client = MagicMock()
        client.configured = True
        client.search.return_value = [
            {"title": "Ada", "url": "https://mit.edu/ada", "description": "Faculty"}
        ]
        provider = ExpertFinderWebSearchToolset(client=client)
        # Act
        result, stop = provider.as_toolset().dispatch(
            WEB_SEARCH, {"query": "Ada Expert MIT email"}
        )
        # Assert
        self.assertFalse(stop)
        self.assertEqual(len(result["results"]), 1)
        self.assertIn("https://mit.edu/ada", provider.provenance)

    def test_errors_when_unconfigured(self):
        # Arrange
        client = MagicMock()
        client.configured = False
        toolset = ExpertFinderWebSearchToolset(client=client).as_toolset()
        # Act
        result, _stop = toolset.dispatch(WEB_SEARCH, {"query": "Ada MIT email"})
        # Assert
        self.assertIn("not configured", result["error"])
        client.search.assert_not_called()
