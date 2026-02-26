import logging

from django.conf import settings

from utils import sentry
from utils.aws import create_client

logger = logging.getLogger(__name__)

# Default model; can be overridden via settings
BEDROCK_MODEL_ID = getattr(
    settings,
    "RESEARCH_AI_BEDROCK_MODEL_ID",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
)


class BedrockLLMService:

    def __init__(self):
        self.enabled = getattr(settings, "BEDROCK_PROCESSING_ENABLED", False)
        if self.enabled:
            self.bedrock_client = create_client("bedrock-runtime")
        else:
            self.bedrock_client = None
        self.model_id = BEDROCK_MODEL_ID

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
            temperature: Sampling temperature (0 = deterministic).

        Returns:
            Generated text from the model.

        Raises:
            RuntimeError: If Bedrock is disabled or invocation fails.
        """
        if not self.enabled or not self.bedrock_client:
            raise RuntimeError("Bedrock processing is disabled")

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
                inferenceConfig={
                    "maxTokens": max_tokens,
                    "temperature": temperature,
                },
            )
        except Exception as e:
            sentry.log_error(e, message="Bedrock Converse API call failed")
            logger.exception("Bedrock invoke failed")
            raise RuntimeError(f"Bedrock invoke failed: {e}") from e

        if "output" not in response or not response["output"].get("message"):
            logger.error("Invalid Bedrock response: missing output message")
            raise RuntimeError("Invalid Bedrock response: missing output message")

        message = response["output"]["message"]
        content = message.get("content", [])
        if not content:
            return ""

        parts = []
        for block in content:
            if "text" in block:
                parts.append(block["text"])
        return "".join(parts)
