from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from research_ai.services.openai_expert_finder_service import (
    OpenAIExpertFinderService,
)


class OpenAIExpertFinderServiceTests(TestCase):
    @override_settings(OPENAI_API_KEY="sk-test")
    @patch("research_ai.services.openai_llm_service.OpenAI")
    def test_defaults_to_expert_finder_token_budget(self, mock_openai_cls):
        # Arrange
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        resp = MagicMock()
        resp.output_text = "| Name |"
        mock_client.responses.create.return_value = resp
        # Act: no max_tokens -> the subclass's larger default is used.
        OpenAIExpertFinderService().invoke("sys", "user")
        # Assert
        kwargs = mock_client.responses.create.call_args.kwargs
        self.assertEqual(kwargs["max_output_tokens"], 16_384)

    @override_settings(OPENAI_API_KEY="sk-test")
    @patch("research_ai.services.openai_llm_service.sentry.log_error")
    @patch("research_ai.services.openai_llm_service.OpenAI")
    def test_failure_uses_expert_finder_label(self, mock_openai_cls, mock_sentry):
        # Arrange: both invoke paths fail.
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.responses.create.side_effect = ValueError("x")
        mock_client.chat.completions.create.side_effect = ConnectionError("y")
        # Act / Assert: the subclass label surfaces in the raised error.
        with self.assertRaises(RuntimeError) as ctx:
            OpenAIExpertFinderService().invoke("s", "u")
        self.assertIn("OpenAI expert finder failed", str(ctx.exception))
        mock_sentry.assert_called_once()
