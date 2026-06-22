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
    TextBlock,
    ToolResultBlock,
)

logger = logging.getLogger(__name__)


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
        max_iterations: int = 12,
        max_tokens: int = 4096,
        temperature: float = 0.0,
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

            if not turn.tool_calls:
                # Model answered in plain text without calling a tool: done.
                return AgentResult(
                    messages=messages,
                    final_text=turn.text,
                    stop_reason="end_turn",
                    iterations=iteration,
                )

            result_blocks: list[ToolResultBlock] = []
            stop = False
            for call in turn.tool_calls:
                result, tool_stop = self.toolset.dispatch(call.name, call.input)
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
                return AgentResult(
                    messages=messages,
                    final_text=turn.text,
                    stop_reason="stop_tool",
                    iterations=iteration,
                )

        raise RuntimeError(f"Agent exceeded {self.max_iterations} iterations")
