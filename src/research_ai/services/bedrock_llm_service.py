import logging
from typing import Callable

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

# Dispatcher contract for ``run_tool_loop``: given a tool name and the model's
# parsed tool input, return ``(result, stop)``. ``result`` is sent back to the
# model as the tool result (must be JSON-serializable); ``stop=True`` ends the
# loop after the result is delivered (used by terminal "submit" tools).
ToolDispatch = Callable[[str, dict], tuple[dict, bool]]


def _message_text(message: dict) -> str:
    """Concatenate the text blocks of a Converse assistant message."""
    return "".join(
        block["text"] for block in message.get("content", []) if "text" in block
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

    def run_tool_loop(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        tools: list[dict],
        dispatch: ToolDispatch,
        max_iterations: int = 12,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> str:
        """
        Run a Bedrock Converse tool-use loop until the model stops calling tools.

        The model is given ``tools`` (Converse ``toolSpec`` dicts) and drives the
        conversation: each tool-use block is handed to ``dispatch`` and the result
        is fed back as a ``toolResult``. A dispatcher that returns ``stop=True``
        (a terminal "submit" tool) ends the loop after its result is delivered.

        Args:
            system_prompt: System instruction for the model.
            user_prompt: Opening user message.
            tools: Converse ``toolSpec`` dicts, e.g. ``{"toolSpec": {...}}``.
            dispatch: Maps ``(tool_name, tool_input) -> (result, stop)``.
            max_iterations: Hard cap on model turns before giving up.
            max_tokens: Max tokens per model turn.
            temperature: Sampling temperature (0 = deterministic).

        Returns:
            The final assistant message text (often empty when the model ends on
            a tool call).

        Raises:
            RuntimeError: If invocation fails or the loop exceeds ``max_iterations``.
        """
        messages: list[dict] = [{"role": "user", "content": [{"text": user_prompt}]}]
        tool_config = {"tools": tools}

        for _ in range(max_iterations):
            try:
                response = self.bedrock_client.converse(
                    modelId=self.model_id,
                    system=[{"text": system_prompt}],
                    messages=messages,
                    toolConfig=tool_config,
                    inferenceConfig={
                        "maxTokens": max_tokens,
                        "temperature": temperature,
                    },
                )
            except Exception as e:
                sentry.log_error(e, message="Bedrock Converse tool loop failed")
                logger.exception("Bedrock run_tool_loop failed")
                raise RuntimeError(f"Bedrock run_tool_loop failed: {e}") from e

            message = (response.get("output") or {}).get("message")
            if not message:
                raise RuntimeError("Invalid Bedrock response: missing output message")
            messages.append(message)

            tool_uses = [
                block["toolUse"]
                for block in message.get("content", [])
                if "toolUse" in block
            ]
            if not tool_uses:
                # Model answered in plain text without calling a tool: done.
                return _message_text(message)

            tool_results = []
            stop = False
            for tool_use in tool_uses:
                result, tool_stop = dispatch(
                    tool_use["name"], tool_use.get("input") or {}
                )
                stop = stop or tool_stop
                tool_results.append(
                    {
                        "toolResult": {
                            "toolUseId": tool_use["toolUseId"],
                            "content": [{"json": result}],
                        }
                    }
                )
            messages.append({"role": "user", "content": tool_results})

            if stop:
                return _message_text(message)

        raise RuntimeError(
            f"Bedrock run_tool_loop exceeded {max_iterations} iterations"
        )
