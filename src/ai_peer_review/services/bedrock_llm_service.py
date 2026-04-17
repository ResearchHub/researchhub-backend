import logging

from django.conf import settings

from utils import sentry
from utils.aws import bedrock_runtime_client

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

BEDROCK_MODEL_ID = getattr(
    settings,
    "AI_PEER_REVIEW_BEDROCK_MODEL_ID",
    getattr(settings, "RESEARCH_AI_BEDROCK_MODEL_ID", _DEFAULT_MODEL),
)


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
                inferenceConfig={
                    "maxTokens": max_tokens,
                    "temperature": temperature,
                },
            )
        except Exception as e:
            sentry.log_error(
                e,
                message="Bedrock Converse API call failed (ai_peer_review)",
            )
            logger.exception("Bedrock invoke failed")
            raise RuntimeError(f"Bedrock invoke failed: {e}") from e

        if "output" not in response or not response["output"].get("message"):
            logger.error("Invalid Bedrock response: missing output message")
            raise RuntimeError("Invalid Bedrock response: missing output message")

        message = response["output"]["message"]
        content = message.get("content", [])
        if not content:
            return ""

        parts: list[str] = []
        for block in content:
            if "text" in block:
                parts.append(block["text"])
        return "".join(parts)
