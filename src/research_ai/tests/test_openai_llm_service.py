from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import TestCase, override_settings

from research_ai.services.openai_llm_service import OpenAIWebSearchLLMService


class OpenAIWebSearchLLMServiceTests(TestCase):
    """Cover invoke paths: missing key, Responses API, chat fallback, failures."""

    def test_missing_api_key_raises_before_any_client_call(self):
        # Arrange
        with override_settings(OPENAI_API_KEY=""):
            svc = OpenAIWebSearchLLMService()
        # Act / Assert
        self.assertIsNone(svc._client)
        with self.assertRaises(RuntimeError) as ctx:
            svc.invoke("system", "user")
        self.assertIn("OPENAI_API_KEY", str(ctx.exception))

    @override_settings(OPENAI_API_KEY="sk-test-key")
    @patch("research_ai.services.openai_llm_service.OpenAI")
    def test_invoke_uses_responses_api_with_web_search(self, mock_openai_cls):
        # Arrange
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        resp = MagicMock()
        resp.output_text = '  {"choice": 0}  '
        mock_client.responses.create.return_value = resp
        # Act
        svc = OpenAIWebSearchLLMService()
        out = svc.invoke("You are helpful.", "Disambiguate.", max_tokens=512)
        # Assert
        self.assertEqual(out, '{"choice": 0}')
        kwargs = mock_client.responses.create.call_args.kwargs
        self.assertEqual(kwargs["model"], settings.OPENAI_MODEL)
        self.assertEqual(kwargs["instructions"], "You are helpful.")
        self.assertEqual(kwargs["input"], "Disambiguate.")
        self.assertEqual(kwargs["tools"], [{"type": "web_search"}])
        self.assertEqual(kwargs["max_output_tokens"], 512)
        mock_client.chat.completions.create.assert_not_called()

    @override_settings(OPENAI_API_KEY="sk-test")
    @patch("research_ai.services.openai_llm_service.OpenAI")
    def test_invoke_falls_back_to_chat_when_responses_raises(self, mock_openai_cls):
        # Arrange
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.responses.create.side_effect = ValueError("responses unavailable")
        completion = MagicMock()
        completion.choices = [MagicMock()]
        completion.choices[0].message.content = "  fallback  "
        mock_client.chat.completions.create.return_value = completion
        # Act
        svc = OpenAIWebSearchLLMService()
        out = svc.invoke("sys", "user", max_tokens=100)
        # Assert
        self.assertEqual(out, "fallback")
        mock_client.responses.create.assert_called_once()
        cc_kwargs = mock_client.chat.completions.create.call_args.kwargs
        self.assertEqual(cc_kwargs["max_completion_tokens"], 100)
        self.assertNotIn("max_tokens", cc_kwargs)

    @override_settings(OPENAI_API_KEY="sk-test")
    @patch("research_ai.services.openai_llm_service.OpenAI")
    def test_invoke_returns_empty_string_when_output_text_empty(self, mock_openai_cls):
        # Arrange
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        resp = MagicMock()
        resp.output_text = ""
        mock_client.responses.create.return_value = resp
        # Act / Assert
        self.assertEqual(OpenAIWebSearchLLMService().invoke("s", "u"), "")

    @override_settings(OPENAI_API_KEY="sk-test")
    @patch("research_ai.services.openai_llm_service.OpenAI")
    def test_invoke_chat_completion_null_content_returns_empty(self, mock_openai_cls):
        # Arrange: web search fails, chat fallback returns null content.
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.responses.create.side_effect = RuntimeError("no responses")
        completion = MagicMock()
        completion.choices = [MagicMock()]
        completion.choices[0].message.content = None
        mock_client.chat.completions.create.return_value = completion
        # Act / Assert
        self.assertEqual(OpenAIWebSearchLLMService().invoke("s", "u"), "")

    @override_settings(OPENAI_API_KEY="sk-test")
    @patch("research_ai.services.openai_llm_service.sentry.log_error")
    @patch("research_ai.services.openai_llm_service.OpenAI")
    def test_invoke_raises_when_both_paths_fail(self, mock_openai_cls, mock_sentry):
        # Arrange
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.responses.create.side_effect = ValueError("responses failed")
        mock_client.chat.completions.create.side_effect = ConnectionError("down")
        # Act / Assert
        svc = OpenAIWebSearchLLMService()
        with self.assertRaises(RuntimeError) as ctx:
            svc.invoke("s", "u")
        self.assertIn("OpenAI web search LLM failed", str(ctx.exception))
        self.assertIsInstance(ctx.exception.__cause__, ConnectionError)
        mock_sentry.assert_called_once()
