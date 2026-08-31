import logging

from django.conf import settings

from research_ai.services.llm_result import LLMTextResult, bedrock_usage
from research_ai.services.usage_budget import record
from utils.aws import create_client

logger = logging.getLogger(__name__)

# Default model; can be overridden via settings
BEDROCK_MODEL_ID = getattr(
    settings,
    "RESEARCH_AI_BEDROCK_MODEL_ID",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
)


class BedrockLLMService:
    def __init__(self, *, user=None, feature: str | None = None):
        self.bedrock_client = create_client("bedrock-runtime")
        self.model_id = BEDROCK_MODEL_ID
        self.user = user
        self.feature = feature

    def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int = 8192,
        temperature: float = 0.0,
    ) -> LLMTextResult:
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
            RuntimeError: If invocation fails.
        """
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
            logger.exception("Bedrock invoke failed")
            raise RuntimeError(f"Bedrock invoke failed: {e}") from e

        if "output" not in response or not response["output"].get("message"):
            logger.error("Invalid Bedrock response: missing output message")
            raise RuntimeError("Invalid Bedrock response: missing output message")

        message = response["output"]["message"]
        content = message.get("content", [])
        usage = bedrock_usage(response)
        if usage is not None and self.feature is not None:
            record(self.user, self.feature, "bedrock", self.model_id, usage)
        if not content:
            return LLMTextResult("", usage)

        parts = [block["text"] for block in content if "text" in block]
        return LLMTextResult("".join(parts), usage)
