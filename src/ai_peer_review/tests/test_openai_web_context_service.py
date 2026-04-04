"""Tests for optional OpenAI web context used in proposal review."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from ai_peer_review.services.openai_web_context_service import (
    PROPOSAL_REVIEW_WEB_MODEL,
    fetch_proposal_review_web_context,
)


class OpenAIWebContextServiceTests(SimpleTestCase):
    def test_returns_empty_when_no_api_key(self):
        with override_settings(OPENAI_API_KEY=""):
            self.assertEqual(
                fetch_proposal_review_web_context("proposal text", "author hint"),
                "",
            )

    @override_settings(OPENAI_API_KEY="sk-test")
    @patch("ai_peer_review.services.openai_web_context_service.OpenAI")
    def test_uses_responses_api_with_web_search(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.output_text = "- Line one https://a.test\n- Line two"
        mock_client.responses.create.return_value = mock_response
        mock_openai_cls.return_value = mock_client

        out = fetch_proposal_review_web_context("p", "a")
        self.assertIn("Line one", out)
        mock_openai_cls.assert_called_once_with(api_key="sk-test")
        kwargs = mock_client.responses.create.call_args.kwargs
        self.assertEqual(kwargs["model"], PROPOSAL_REVIEW_WEB_MODEL)
        self.assertEqual(kwargs["tools"], [{"type": "web_search"}])

    @override_settings(OPENAI_API_KEY="sk-test")
    @patch("ai_peer_review.services.openai_web_context_service.sentry.log_error")
    @patch("ai_peer_review.services.openai_web_context_service.OpenAI")
    def test_falls_back_to_chat_when_responses_fails(self, mock_openai_cls, _sentry):
        mock_client = MagicMock()
        mock_client.responses.create.side_effect = RuntimeError("responses down")
        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(message=MagicMock(content="- fallback bullet"))
        ]
        mock_client.chat.completions.create.return_value = mock_completion
        mock_openai_cls.return_value = mock_client

        out = fetch_proposal_review_web_context("p", "a")
        self.assertEqual(out, "- fallback bullet")
        mock_client.chat.completions.create.assert_called_once()
