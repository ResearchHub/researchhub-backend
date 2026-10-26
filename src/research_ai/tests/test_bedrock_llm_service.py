from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from research_ai.services.bedrock_llm_service import BedrockLLMService


@patch("research_ai.services.bedrock_llm_service.create_client")
class BedrockLLMServiceTests(SimpleTestCase):
    def _service(self, mock_create_client, model_id: str):
        client = MagicMock()
        client.converse.return_value = {
            "output": {"message": {"content": [{"text": "x"}]}}
        }
        mock_create_client.return_value = client
        service = BedrockLLMService()
        service.model_id = model_id
        return service, client

    def test_omits_temperature_for_haiku_5_5(self, mock_create_client):
        # Arrange
        service, client = self._service(
            mock_create_client, "us.anthropic.claude-haiku-5-5"
        )

        # Act
        service.invoke("sys", "user", max_tokens=100, temperature=0.0)

        # Assert
        inference_config = client.converse.call_args.kwargs["inferenceConfig"]
        self.assertEqual(inference_config, {"maxTokens": 100})

    def test_sends_temperature_to_models_that_accept_it(self, mock_create_client):
        # Arrange
        service, client = self._service(
            mock_create_client, "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        )

        # Act
        service.invoke("sys", "user", max_tokens=100, temperature=0.0)

        # Assert
        inference_config = client.converse.call_args.kwargs["inferenceConfig"]
        self.assertEqual(inference_config, {"maxTokens": 100, "temperature": 0.0})
