import logging

from research_ai.services.agent.model_capabilities import model_capabilities
from research_ai.services.llm_models import RESEARCH_AI_BEDROCK
from utils.aws import create_client

logger = logging.getLogger(__name__)


class BedrockLLMService:
    def __init__(self):
        self.bedrock_client = create_client("bedrock-runtime")
        self.model_id = RESEARCH_AI_BEDROCK.model_id

    def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int = 8192,
        temperature: float = 0.0,
    ) -> str:
        """
        Invoke Bedrock Converse API with text-only system and user messages.

        Args:
            system_prompt: System instruction for the model.
            user_prompt: User message content.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature (0 = deterministic). Not sent to
                models that reject sampling parameters.

        Returns:
            Generated text from the model.

        Raises:
            RuntimeError: If invocation fails.
        """
        inference_config: dict[str, int | float] = {"maxTokens": max_tokens}
        if model_capabilities("bedrock", self.model_id).temperature:
            inference_config["temperature"] = temperature
        try:
            response = self.bedrock_client.converse(
                modelId=self.model_id,
                system=[{"text": system_prompt}],
                messages=[
                    {
                        "role": "user",
                        "content": [{"text": user_prompt}],
                    }
                ],
                inferenceConfig=inference_config,
            )
        except Exception as e:
            logger.exception("Bedrock invoke failed")
            raise RuntimeError(f"Bedrock invoke failed: {e}") from e

        if "output" not in response or not response["output"].get("message"):
            logger.error("Invalid Bedrock response: missing output message")
            raise RuntimeError("Invalid Bedrock response: missing output message")

        message = response["output"]["message"]
        content = message.get("content", [])
        if not content:
            return ""

        parts = [block["text"] for block in content if "text" in block]
        return "".join(parts)
