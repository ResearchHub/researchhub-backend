import logging

from django.conf import settings

from research_ai.services.agent.model_capabilities import model_capabilities
from utils.aws import bedrock_runtime_client

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "us.anthropic.claude-haiku-5-5"

BEDROCK_MODEL_ID = getattr(
    settings,
    "AI_PEER_REVIEW_BEDROCK_MODEL_ID",
    _DEFAULT_MODEL,
)


def _converse_inference_config(
    model_id: str, *, max_tokens: int, temperature: float
) -> dict:
    config: dict[str, int | float] = {"maxTokens": max_tokens}
    # Models that reject sampling params (Opus 4.7+, Sonnet 5, Haiku 5.5) 400
    # on ``temperature``, so it goes only where it is reviewed.
    if model_capabilities("bedrock", model_id).temperature:
        config["temperature"] = temperature
    return config


class BedrockLLMService:
    """Invoke Bedrock for structured proposal review JSON (and related tasks)."""

    def __init__(self):
        self.bedrock_client = bedrock_runtime_client()
        self.model_id = BEDROCK_MODEL_ID

    def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int = 8192,
        temperature: float = 0.0,
    ) -> str:
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
                inferenceConfig=_converse_inference_config(
                    self.model_id,
                    max_tokens=max_tokens,
                    temperature=temperature,
                ),
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

        parts: list[str] = [block["text"] for block in content if "text" in block]
        return "".join(parts)
