import logging

from django.conf import settings

from research_ai.services.llm_result import LLMTextResult, bedrock_usage
from research_ai.services.usage_budget import record
from utils.aws import bedrock_runtime_client

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

BEDROCK_MODEL_ID = getattr(
    settings,
    "AI_PEER_REVIEW_BEDROCK_MODEL_ID",
    _DEFAULT_MODEL,
)

_BEDROCK_OMIT_TEMPERATURE_SUBSTRINGS: tuple[str, ...] = ("opus-4-7",)


def _converse_inference_config(
    model_id: str, *, max_tokens: int, temperature: float
) -> dict:
    config: dict[str, int | float] = {"maxTokens": max_tokens}
    lower = model_id.lower()
    if not any(s in lower for s in _BEDROCK_OMIT_TEMPERATURE_SUBSTRINGS):
        config["temperature"] = temperature
    return config


class BedrockLLMService:
    """Invoke Bedrock for structured proposal review JSON (and related tasks)."""

    def __init__(self, *, user=None, feature: str = "proposal_review"):
        self.bedrock_client = bedrock_runtime_client()
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
        usage = bedrock_usage(response)
        if usage is not None:
            record(self.user, self.feature, "bedrock", self.model_id, usage)
        if not content:
            return LLMTextResult("", usage)

        parts: list[str] = [block["text"] for block in content if "text" in block]
        return LLMTextResult("".join(parts), usage)
