"""The agent loop: drives multi-turn, tool-using conversations to completion.

This is the neutral generalization of ``BedrockLLMService.run_tool_loop``. It
renders the toolset once, then repeatedly asks the provider to ``complete`` a
turn, dispatching every tool call the model makes and feeding the results back
until the model answers in plain text or a terminal tool stops the run.

The loop is resumable: ``continue_conversation`` appends a user turn to an
existing message list and drives from there, which is what a notebook-style
multi-turn chat needs.
"""

import logging
from dataclasses import dataclass

from research_ai.services.agent.providers.base import LLMProvider
from research_ai.services.agent.tools import Toolset
from research_ai.services.agent.types import (
    Message,
    StopReason,
    TextBlock,
    ToolResultBlock,
)

logger = logging.getLogger(__name__)

# Cap on how much of any single value the trace logs, so a large tool input
# (e.g. a full proposal submission) or result never floods the log.
_LOG_VALUE_LIMIT = 300


def _truncate(text: str, limit: int = _LOG_VALUE_LIMIT) -> str:
    """Collapse whitespace and cap ``text`` to ``limit`` chars for one-line logs."""
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "…"


def _compact_args(args) -> str:
    """One-line, length-capped view of a tool call's input for tracing.

    Strings are truncated, and lists/dicts are shown by size/keys rather than
    dumped, so the "what was called with" reads at a glance without logging a
    whole proposal body or works list.
    """
    if not isinstance(args, dict):
        return _truncate(repr(args))
    parts = []
    for key, value in args.items():
        if isinstance(value, str):
            shown = _truncate(value, 80)
        elif isinstance(value, (list, tuple)):
            shown = f"[{len(value)} items]"
        elif isinstance(value, dict):
            shown = "{" + ", ".join(map(str, value.keys())) + "}"
        else:
            shown = repr(value)
        parts.append(f"{key}={shown}")
    return _truncate(", ".join(parts))


def _summarize_result(result) -> str:
    """One-line summary of a tool result: error text, or the dict's shape."""
    if isinstance(result, dict):
        if "error" in result:
            return f"error: {_truncate(result['error'], 120)}"
        return "{" + ", ".join(map(str, result.keys())) + "}"
    if isinstance(result, (list, tuple)):
        return f"[{len(result)} items]"
    return _truncate(repr(result))


@dataclass
class AgentResult:
    """The outcome of an agent run.

    Args:
        messages: The full conversation, ready to persist or resume.
        final_text: The assistant's last text (often empty when it ends on a
            terminal tool call).
        stop_reason: ``"end_turn"`` (model answered in plain text) or
            ``"stop_tool"`` (a terminal tool ended the run).
        iterations: Number of model turns taken.
    """

    messages: list[Message]
    final_text: str
    stop_reason: str
    iterations: int


class Agent:
    """Drives a provider + toolset over multiple turns until completion."""

    def __init__(
        self,
        provider: LLMProvider,
        toolset: Toolset,
        *,
        system_prompt: str,
        max_iterations: int,
        max_tokens: int,
        temperature: float,
    ):
        self.provider = provider
        self.toolset = toolset
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens
        self.temperature = temperature

    def run(self, user_prompt: str, *, on_event=None) -> AgentResult:
        """Drive a fresh conversation from ``user_prompt`` to completion."""
        messages = [Message(role="user", content=[TextBlock(text=user_prompt)])]
        return self._drive(messages, on_event=on_event)

    def continue_conversation(
        self,
        messages: list[Message],
        user_message: str,
        *,
        on_event=None,
    ) -> AgentResult:
        """Append a user turn to ``messages`` and drive (resumable multi-turn).

        ``messages`` is copied, not mutated; the updated list is returned on the
        ``AgentResult``.
        """
        messages = list(messages) + [
            Message(role="user", content=[TextBlock(text=user_message)])
        ]
        return self._drive(messages, on_event=on_event)

    def _drive(self, messages: list[Message], *, on_event=None) -> AgentResult:
        # ``on_event`` is an unused placeholder for the future streaming hook;
        # it is threaded toward ``complete`` but streaming is not implemented.
        rendered_tools = self.toolset.render_specs(self.provider)
        logger.info(
            "agent run start: tools=[%s] max_iterations=%d",
            ", ".join(self.toolset.names),
            self.max_iterations,
        )

        for iteration in range(1, self.max_iterations + 1):
            turn = self.provider.complete(
                system_prompt=self.system_prompt,
                messages=messages,
                rendered_tools=rendered_tools,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            messages.append(
                Message(
                    role="assistant",
                    content=[*turn.text_blocks, *turn.tool_calls],
                )
            )

            # The assistant's text on a tool-calling turn is its stated reason for
            # the calls -- log it so the trace shows *why* a tool was picked.
            if turn.text.strip():
                logger.info("iter %d reasoning: %s", iteration, _truncate(turn.text))

            if not turn.tool_calls and turn.stop_reason == StopReason.END_TURN:
                # Model answered in plain text without calling a tool: done.
                logger.info("iter %d end_turn: agent answered in plain text", iteration)
                return AgentResult(
                    messages=messages,
                    final_text=turn.text,
                    stop_reason=turn.stop_reason.value,
                    iterations=iteration,
                )
            if not turn.tool_calls:
                raise RuntimeError(
                    "Provider stopped without completing the agent run: "
                    f"{turn.stop_reason.value}"
                )

            result_blocks: list[ToolResultBlock] = []
            stop = False
            for call in turn.tool_calls:
                logger.info(
                    "iter %d -> %s(%s)", iteration, call.name, _compact_args(call.input)
                )
                result, tool_stop = self.toolset.dispatch(call.name, call.input)
                logger.info(
                    "iter %d <- %s: %s%s",
                    iteration,
                    call.name,
                    _summarize_result(result),
                    " [terminal]" if tool_stop else "",
                )
                stop = stop or tool_stop
                result_blocks.append(
                    ToolResultBlock(
                        tool_use_id=call.id,
                        content=result,
                        is_error=isinstance(result, dict) and "error" in result,
                    )
                )
            messages.append(Message(role="user", content=result_blocks))

            if stop:
                logger.info("iter %d stop_tool: terminal tool ended the run", iteration)
                return AgentResult(
                    messages=messages,
                    final_text=turn.text,
                    stop_reason="stop_tool",
                    iterations=iteration,
                )

        logger.info("agent hit iteration cap of %d", self.max_iterations)
        raise RuntimeError(f"Agent exceeded {self.max_iterations} iterations")
