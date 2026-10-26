import logging

from django.conf import settings

from research_ai.services.agent.model_capabilities import model_capabilities
from utils.aws import create_client

logger = logging.getLogger(__name__)

# Default model; can be overridden via settings
BEDROCK_MODEL_ID = getattr(
    settings,
    "RESEARCH_AI_BEDROCK_MODEL_ID",
    "us.anthropic.claude-haiku-5-5",
)


class BedrockLLMService:
    def __init__(self):
        self.bedrock_client = create_client("bedrock-runtime")
        self.model_id = BEDROCK_MODEL_ID

    def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int = 8192,
        temperature: float = 0.0,
        disable_thinking: bool = False,
    ) -> str:
        """
        Invoke Bedrock Converse API with text-only system and user messages.

        Args:
            system_prompt: System instruction for the model.
            user_prompt: User message content.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature (0 = deterministic). Not sent to
                models that reject sampling parameters.
            disable_thinking: Turn thinking off where the model lets it be
                turned off. Models that never think by default need nothing
                sent; models that always think keep thinking.

        Returns:
            Generated text from the model.

        Raises:
            RuntimeError: If invocation fails.
        """
        inference_config: dict[str, int | float] = {"maxTokens": max_tokens}
        # Models that reject sampling params (Opus 4.7+, Sonnet 5, Haiku 5.5)
        # 400 on ``temperature``, so it goes only where it is reviewed.
        if model_capabilities("bedrock", self.model_id).temperature:
            inference_config["temperature"] = temperature
        extra_fields: dict = {}
        if (
            disable_thinking
            and "disabled" in model_capabilities("bedrock", self.model_id).thinking
        ):
            extra_fields["additionalModelRequestFields"] = {
                "thinking": {"type": "disabled"}
            }
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
                **extra_fields,
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
