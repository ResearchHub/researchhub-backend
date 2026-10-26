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

    def test_disable_thinking_turns_thinking_off_on_haiku_5_5(self, mock_create_client):
        # Arrange
        service, client = self._service(
            mock_create_client, "us.anthropic.claude-haiku-5-5"
        )

        # Act
        service.invoke("sys", "user", max_tokens=100, disable_thinking=True)

        # Assert
        self.assertEqual(
            client.converse.call_args.kwargs["additionalModelRequestFields"],
            {"thinking": {"type": "disabled"}},
        )

    def test_thinking_is_left_alone_by_default(self, mock_create_client):
        # Arrange
        service, client = self._service(
            mock_create_client, "us.anthropic.claude-haiku-5-5"
        )

        # Act
        service.invoke("sys", "user", max_tokens=100)

        # Assert
        self.assertNotIn(
            "additionalModelRequestFields", client.converse.call_args.kwargs
        )

    def test_disable_thinking_sends_nothing_to_models_without_the_mode(
        self, mock_create_client
    ):
        # Arrange: Haiku 4.5 never thinks unless asked; Opus 5.5 always thinks.
        for model_id in (
            "us.anthropic.claude-haiku-4-5-20251001-v1:0",
            "us.anthropic.claude-opus-5-5",
        ):
            with self.subTest(model_id=model_id):
                service, client = self._service(mock_create_client, model_id)

                # Act
                service.invoke("sys", "user", max_tokens=100, disable_thinking=True)

                # Assert
                self.assertNotIn(
                    "additionalModelRequestFields", client.converse.call_args.kwargs
                )
