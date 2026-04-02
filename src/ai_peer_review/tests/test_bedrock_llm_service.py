from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from ai_peer_review.services.bedrock_llm_service import BedrockLLMService


class BedrockLLMServiceTests(SimpleTestCase):
    def test_invoke_joins_text_blocks(self):
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [
                        {"text": "part-a"},
                        {"text": "part-b"},
                    ]
                }
            }
        }
        with patch(
            "ai_peer_review.services.bedrock_llm_service.create_client",
            return_value=mock_client,
        ):
            svc = BedrockLLMService()
            out = svc.invoke("system", "user prompt")
        self.assertEqual(out, "part-apart-b")
        mock_client.converse.assert_called_once()

    def test_invoke_empty_content_list_returns_empty_string(self):
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {"message": {"content": []}}
        }
        with patch(
            "ai_peer_review.services.bedrock_llm_service.create_client",
            return_value=mock_client,
        ):
            svc = BedrockLLMService()
            out = svc.invoke("s", "u")
        self.assertEqual(out, "")

    def test_invoke_converse_error_wraps_runtime_error(self):
        mock_client = MagicMock()
        mock_client.converse.side_effect = OSError("network")
        with patch(
            "ai_peer_review.services.bedrock_llm_service.create_client",
            return_value=mock_client,
        ):
            svc = BedrockLLMService()
            with self.assertRaises(RuntimeError) as ctx:
                svc.invoke("s", "u")
        self.assertIn("Bedrock invoke failed", str(ctx.exception))

    def test_invoke_missing_output_message_raises(self):
        mock_client = MagicMock()
        mock_client.converse.return_value = {"output": {}}
        with patch(
            "ai_peer_review.services.bedrock_llm_service.create_client",
            return_value=mock_client,
        ):
            svc = BedrockLLMService()
            with self.assertRaises(RuntimeError) as ctx:
                svc.invoke("s", "u")
        self.assertIn("Invalid Bedrock response", str(ctx.exception))
