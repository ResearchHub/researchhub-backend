"""Unit tests for GPT basic-engine search + SES gate."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from research_ai.services.expert_finder.gpt_finder import run_gpt_expert_finder


class RunGptExpertFinderTests(SimpleTestCase):
    @patch("research_ai.services.expert_finder.gpt_finder.EmailValidationService")
    @patch("research_ai.services.expert_finder.gpt_finder.OpenAIExpertFinderService")
    def test_parses_json_and_applies_ses_gate(self, mock_openai_cls, mock_email_cls):
        # Arrange
        openai = MagicMock()
        openai.model_id = "gpt-5.4-mini"
        openai.invoke.return_value = (
            '{"experts":[{"email":"ok@mit.edu","first_name":"Ok",'
            '"last_name":"Person","affiliation":"MIT","expertise":"X",'
            '"notes":"n","sources":[]}]}'
        )
        mock_openai_cls.return_value = openai

        email_svc = MagicMock()
        email_svc.gate_submitted_experts.return_value = (
            [
                {
                    "email": "ok@mit.edu",
                    "first_name": "Ok",
                    "last_name": "Person",
                    "affiliation": "MIT",
                    "expertise": "X",
                    "notes": "n",
                    "sources": [],
                }
            ],
            [],
        )
        mock_email_cls.return_value = email_svc

        # Act
        result = run_gpt_expert_finder(
            query="autophagy research",
            expert_count=3,
            expertise_level=["ALL_LEVELS"],
            region_filter="ALL_REGIONS",
        )

        # Assert
        self.assertEqual(result["llm_model"], "openai:gpt-5.4-mini")
        self.assertEqual(len(result["experts"]), 1)
        self.assertEqual(result["experts"][0]["email"], "ok@mit.edu")
        email_svc.gate_submitted_experts.assert_called_once()
        openai.invoke.assert_called_once()

    @patch("research_ai.services.expert_finder.gpt_finder.EmailValidationService")
    @patch("research_ai.services.expert_finder.gpt_finder.OpenAIExpertFinderService")
    def test_ses_drops_invalid_emails(self, mock_openai_cls, mock_email_cls):
        # Arrange
        openai = MagicMock()
        openai.model_id = "gpt-5.4-mini"
        openai.invoke.return_value = (
            '{"experts":[{"email":"bad@example.com","first_name":"B",'
            '"last_name":"Ad","sources":[]}]}'
        )
        mock_openai_cls.return_value = openai

        email_svc = MagicMock()
        email_svc.gate_submitted_experts.return_value = (
            [],
            ["experts[0] (bad@example.com): mailbox does not exist"],
        )
        mock_email_cls.return_value = email_svc

        # Act
        result = run_gpt_expert_finder(
            query="topic",
            expert_count=2,
            expertise_level=["ALL_LEVELS"],
            region_filter="ALL_REGIONS",
        )

        # Assert
        self.assertEqual(result["experts"], [])
        self.assertTrue(result["errors"])
