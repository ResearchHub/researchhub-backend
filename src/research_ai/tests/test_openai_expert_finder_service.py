"""Unit tests for OpenAIExpertFinderService (mocked OpenAI client)."""

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from research_ai.services.openai_expert_finder_service import (
    OPENAI_EXPERT_FINDER_MODEL,
    OpenAIExpertFinderService,
)


class OpenAIExpertFinderServiceTests(TestCase):
    """Cover invoke paths: missing key, Responses API, chat fallback, failures."""

    def test_missing_api_key_raises_before_any_client_call(self):
        with override_settings(OPENAI_API_KEY=""):
            svc = OpenAIExpertFinderService()
        self.assertIsNone(svc._client)
        with self.assertRaises(RuntimeError) as ctx:
            svc.invoke("system", "user")
        self.assertIn("OPENAI_API_KEY", str(ctx.exception))

    @override_settings(OPENAI_API_KEY="sk-test-key")
    @patch("research_ai.services.openai_expert_finder_service.OpenAI")
    def test_invoke_uses_responses_api_with_web_search_and_strips_text(
        self, mock_openai_cls
    ):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        resp = MagicMock()
        resp.output_text = "  | Name | Email |\n  "
        mock_client.responses.create.return_value = resp

        svc = OpenAIExpertFinderService()
        self.assertEqual(svc.model_id, OPENAI_EXPERT_FINDER_MODEL)

        out = svc.invoke(
            "You are helpful.",
            "Find experts.",
            max_tokens=4096,
            temperature=0.1,
        )

        self.assertEqual(out, "| Name | Email |")
        mock_openai_cls.assert_called_once_with(api_key="sk-test-key")
        mock_client.responses.create.assert_called_once()
        kwargs = mock_client.responses.create.call_args.kwargs
        self.assertEqual(kwargs["model"], OPENAI_EXPERT_FINDER_MODEL)
        self.assertEqual(kwargs["instructions"], "You are helpful.")
        self.assertEqual(kwargs["input"], "Find experts.")
        self.assertEqual(kwargs["tools"], [{"type": "web_search"}])
        self.assertEqual(kwargs["max_output_tokens"], 4096)
        self.assertEqual(kwargs["temperature"], 0.1)
        mock_client.chat.completions.create.assert_not_called()

    @override_settings(OPENAI_API_KEY="sk-test")
    @patch("research_ai.services.openai_expert_finder_service.OpenAI")
    def test_invoke_falls_back_to_chat_when_responses_raises(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.responses.create.side_effect = ValueError("responses unavailable")

        completion = MagicMock()
        completion.choices = [MagicMock()]
        completion.choices[0].message.content = "  fallback text  "
        mock_client.chat.completions.create.return_value = completion

        svc = OpenAIExpertFinderService()
        out = svc.invoke("sys", "user", max_tokens=100, temperature=0.0)

        self.assertEqual(out, "fallback text")
        mock_client.responses.create.assert_called_once()
        mock_client.chat.completions.create.assert_called_once()
        cc_kwargs = mock_client.chat.completions.create.call_args.kwargs
        self.assertEqual(cc_kwargs["model"], OPENAI_EXPERT_FINDER_MODEL)
        self.assertEqual(
            cc_kwargs["messages"],
            [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "user"},
            ],
        )
        self.assertEqual(cc_kwargs["max_tokens"], 100)
        self.assertEqual(cc_kwargs["temperature"], 0.0)

    @override_settings(OPENAI_API_KEY="sk-test")
    @patch("research_ai.services.openai_expert_finder_service.OpenAI")
    def test_invoke_returns_empty_string_when_output_text_empty(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        resp = MagicMock()
        resp.output_text = ""
        mock_client.responses.create.return_value = resp

        svc = OpenAIExpertFinderService()
        self.assertEqual(svc.invoke("s", "u"), "")

    @override_settings(OPENAI_API_KEY="sk-test")
    @patch("research_ai.services.openai_expert_finder_service.OpenAI")
    def test_invoke_chat_completion_null_content_returns_empty(
        self, mock_openai_cls
    ):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.responses.create.side_effect = RuntimeError("no responses")

        completion = MagicMock()
        completion.choices = [MagicMock()]
        completion.choices[0].message.content = None
        mock_client.chat.completions.create.return_value = completion

        svc = OpenAIExpertFinderService()
        self.assertEqual(svc.invoke("s", "u"), "")

    @override_settings(OPENAI_API_KEY="sk-test")
    @patch("research_ai.services.openai_expert_finder_service.sentry.log_error")
    @patch("research_ai.services.openai_expert_finder_service.OpenAI")
    def test_invoke_raises_when_both_paths_fail(self, mock_openai_cls, mock_sentry):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.responses.create.side_effect = ValueError("responses failed")
        mock_client.chat.completions.create.side_effect = ConnectionError("network down")

        svc = OpenAIExpertFinderService()
        with self.assertRaises(RuntimeError) as ctx:
            svc.invoke("s", "u")
        self.assertIn("OpenAI expert finder failed", str(ctx.exception))
        self.assertIsInstance(ctx.exception.__cause__, ConnectionError)
        mock_sentry.assert_called_once()
