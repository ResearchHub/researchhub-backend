from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from ai_peer_review.services.bedrock_llm_service import (
    BedrockLLMService,
)
from ai_peer_review.services.openai_web_context_service import (
    OPENAI_WEB_CONTEXT_MODEL,
    OpenAIReviewContextService,
)


class BedrockLLMServiceTests(SimpleTestCase):
    @patch("ai_peer_review.services.bedrock_llm_service.bedrock_runtime_client")
    def test_invoke_returns_joined_text(self, mock_create_client):
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [{"text": "hello"}, {"text": " world"}],
                }
            }
        }

        svc = BedrockLLMService()
        svc.model_id = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        out = svc.invoke("sys", "user", max_tokens=100, temperature=0.1)

        self.assertEqual(out, "hello world")
        mock_client.converse.assert_called_once()
        kwargs = mock_client.converse.call_args.kwargs
        self.assertEqual(kwargs["modelId"], svc.model_id)
        self.assertEqual(kwargs["system"], [{"text": "sys"}])
        self.assertEqual(kwargs["messages"][0]["role"], "user")
        self.assertEqual(kwargs["inferenceConfig"]["maxTokens"], 100)

    @patch("ai_peer_review.services.bedrock_llm_service.bedrock_runtime_client")
    def test_invoke_omits_temperature_for_opus_4_7(self, mock_create_client):
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client
        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "x"}]}}
        }
        svc = BedrockLLMService()
        svc.model_id = "us.anthropic.claude-opus-4-7-20250514-v1:0"
        svc.invoke("s", "u", max_tokens=50, temperature=0.1)
        ic = mock_client.converse.call_args.kwargs["inferenceConfig"]
        self.assertEqual(ic, {"maxTokens": 50})

    @patch("ai_peer_review.services.bedrock_llm_service.bedrock_runtime_client")
    def test_invoke_raises_on_client_error(self, mock_create_client):
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client
        mock_client.converse.side_effect = RuntimeError("aws down")

        svc = BedrockLLMService()
        with self.assertRaises(RuntimeError) as ctx:
            svc.invoke("s", "u")
        self.assertIn("Bedrock invoke failed", str(ctx.exception))


class OpenAIReviewContextServiceTests(SimpleTestCase):
    def test_build_user_prompt_truncates_long_proposal(self):
        svc = OpenAIReviewContextService()
        long_text = "x" * 30000
        prompt = svc.build_user_prompt(
            proposal_excerpt=long_text,
            researcher_display_name="Dr X",
            institutional_affiliation="Inst Y",
        )
        self.assertIn("[TRUNCATED]", prompt)
        self.assertIn("Dr X", prompt)
        self.assertIn("Inst Y", prompt)

    def test_missing_api_key_raises(self):
        with override_settings(OPENAI_API_KEY=""):
            svc = OpenAIReviewContextService()
        self.assertIsNone(svc._client)
        with self.assertRaises(RuntimeError) as ctx:
            svc.invoke("a", "b")
        self.assertIn("OPENAI_API_KEY", str(ctx.exception))

    @override_settings(OPENAI_API_KEY="sk-test")
    @patch("ai_peer_review.services.openai_web_context_service.OpenAI")
    def test_invoke_uses_responses_with_web_search(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        resp = MagicMock()
        resp.output_text = "  - bullet  "
        mock_client.responses.create.return_value = resp

        svc = OpenAIReviewContextService()
        self.assertEqual(svc.model_id, OPENAI_WEB_CONTEXT_MODEL)
        out = svc.invoke("sys", "user", max_tokens=512, temperature=0.0)
        self.assertEqual(out, "- bullet")
        kwargs = mock_client.responses.create.call_args.kwargs
        self.assertEqual(kwargs["tools"], [{"type": "web_search"}])
        self.assertEqual(kwargs["max_output_tokens"], 512)
        mock_client.chat.completions.create.assert_not_called()

    @override_settings(OPENAI_API_KEY="sk-test")
    @patch("ai_peer_review.services.openai_web_context_service.OpenAI")
    def test_invoke_falls_back_to_chat(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.responses.create.side_effect = ValueError("no responses")
        completion = MagicMock()
        completion.choices = [MagicMock()]
        completion.choices[0].message.content = "fallback"
        mock_client.chat.completions.create.return_value = completion

        svc = OpenAIReviewContextService()
        self.assertEqual(svc.invoke("s", "u"), "fallback")
        mock_client.chat.completions.create.assert_called_once()
