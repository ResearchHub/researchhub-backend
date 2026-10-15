"""Refusal fallback across models.

``RoutedProvider`` re-sends a turn its model refused to a fallback model. The
refusal is usually caused by the conversation itself, which every later message
still carries, so a conversation the fallback has answered stays on it.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from research_ai.services.agent.providers.base import LLMProvider
from research_ai.services.agent.tools import Tool
from research_ai.services.agent.types import (
    AssistantTurn,
    Block,
    Message,
    ProviderStreamEvent,
    ServerToolBlock,
    StopReason,
    StreamReset,
    TextBlock,
    ToolUseBlock,
    TurnUsage,
)

logger = logging.getLogger(__name__)

# ``provider_state`` key naming the model that wrote a turn. Only set on turns
# not written by the conversation's own model.
STATE_KEY = "router"

_MAX_SERVER_TOOL_TEXT = 2_000


class RoutedProvider(LLMProvider):
    """Runs a conversation on ``primary`` until it refuses a turn.

    The refused turn goes to ``fallback_ref`` and so does the rest of the
    conversation. ``build`` makes the provider for a model ref other than the
    primary's.
    """

    def __init__(
        self,
        *,
        primary_ref: str,
        primary: LLMProvider,
        fallback_ref: str | None,
        build: Callable[[str], LLMProvider],
    ):
        self.primary_ref = primary_ref
        self.fallback_ref = fallback_ref if fallback_ref != primary_ref else None
        self.model_id = getattr(primary, "model_id", None)
        self._providers = {primary_ref: primary}
        self._build = build
        self._rendered_tools: dict[str, Any] = {}

    @property
    def native_tool_names(self) -> frozenset[str]:
        """Empty, so toolsets keep the local tools another model may need."""
        return frozenset()

    def render_tools(self, tools: list[Tool]) -> list[Tool]:
        # Rendered per model when a request is made: a run can change model.
        self._rendered_tools = {}
        return list(tools)

    def complete(
        self,
        *,
        system_prompt: str,
        messages: list[Message],
        rendered_tools: Any,
        max_tokens: int | None,
        temperature: float,
        before_retry: Callable[[], None] | None = None,
        on_usage: Callable[[TurnUsage], None] | None = None,
    ) -> AssistantTurn:
        return self.complete_with_events(
            system_prompt=system_prompt,
            messages=messages,
            rendered_tools=rendered_tools,
            max_tokens=max_tokens,
            temperature=temperature,
            before_retry=before_retry,
            on_usage=on_usage,
        )

    def complete_with_events(
        self,
        *,
        system_prompt: str,
        messages: list[Message],
        rendered_tools: Any,
        max_tokens: int | None,
        temperature: float,
        on_event: Callable[[ProviderStreamEvent], None] | None = None,
        before_retry: Callable[[], None] | None = None,
        on_usage: Callable[[TurnUsage], None] | None = None,
    ) -> AssistantTurn:
        # A conversation moved off its own model stays where it moved to.
        ref = next(
            (model for model in map(written_by, reversed(messages)) if model),
            self.primary_ref,
        )
        while True:
            provider = self._provider(ref)
            turn = provider.complete_with_events(
                system_prompt=system_prompt,
                messages=self._replayable(messages, ref),
                rendered_tools=self._tools_for(ref, rendered_tools or []),
                max_tokens=max_tokens,
                temperature=temperature,
                on_event=on_event,
                before_retry=before_retry,
                on_usage=self._charged(on_usage, ref),
            )
            if (
                turn.stop_reason is not StopReason.CONTENT_FILTERED
                or ref != self.primary_ref
                or self.fallback_ref is None
            ):
                return self._stamped(turn, ref)
            logger.warning(
                "model router: %s refused a turn, sending it to %s (stop_details=%r)",
                ref,
                self.fallback_ref,
                turn.stop_details,
            )
            ref = self.fallback_ref
            if before_retry is not None:
                before_retry()
            if on_event is not None:
                # The refused attempt may have streamed part of an answer.
                on_event(StreamReset())

    def _provider(self, ref: str) -> LLMProvider:
        if ref not in self._providers:
            self._providers[ref] = self._build(ref)
        return self._providers[ref]

    def _tools_for(self, ref: str, tools: list[Tool]) -> Any:
        if ref not in self._rendered_tools:
            provider = self._provider(ref)
            # A model that runs a tool server-side declares it in place of ours.
            self._rendered_tools[ref] = provider.render_tools(
                [tool for tool in tools if tool.name not in provider.native_tool_names]
            )
        return self._rendered_tools[ref]

    def _replayable(self, messages: list[Message], ref: str) -> list[Message]:
        """``messages`` as model ``ref`` can replay them."""
        replayable = []
        for message in messages:
            if message.role == "assistant":
                if (written_by(message) or self.primary_ref) != ref:
                    # Reasoning, server-side tool blocks and continuation state
                    # replay only on the model that wrote them.
                    message = Message(
                        role="assistant", content=_portable(message.content)
                    )
                if not message.content:
                    # A refused turn; providers reject an empty one on replay.
                    continue
            replayable.append(message)
        return replayable

    def _charged(
        self, on_usage: Callable[[TurnUsage], None] | None, ref: str
    ) -> Callable[[TurnUsage], None] | None:
        if on_usage is None or ref == self.primary_ref:
            return on_usage
        return lambda usage: on_usage(replace(usage, model_ref=ref))

    def _stamped(self, turn: AssistantTurn, ref: str) -> AssistantTurn:
        if ref == self.primary_ref:
            return turn
        state = {**turn.provider_state, STATE_KEY: {"model": ref}}
        stamped: AssistantTurn = replace(turn, provider_state=state)
        return stamped


def written_by(message: Message) -> str | None:
    """The model that wrote ``message`` when it was not the conversation's own."""
    state = message.provider_state.get(STATE_KEY)
    return state.get("model") if isinstance(state, dict) else None


def _portable(blocks: list[Block]) -> list[Block]:
    """A turn's text and tool calls, readable by any model."""
    portable: list[Block] = []
    for block in blocks:
        if isinstance(block, TextBlock) and block.text:
            portable.append(TextBlock(text=block.text))
        elif isinstance(block, ToolUseBlock):
            portable.append(
                ToolUseBlock(id=block.id, name=block.name, input=block.input)
            )
        elif isinstance(block, ServerToolBlock):
            text = _server_tool_text(block.data)
            if text:
                portable.append(TextBlock(text=text))
    return portable


def _server_tool_text(data: dict) -> str:
    """A server-side tool call or its result as a short note."""
    if data.get("type") == "server_tool_use":
        call = json.dumps(data.get("input") or {}, ensure_ascii=False)
        text = f"[{data.get('name')} call: {call}]"
    else:
        content = data.get("content")
        items = content if isinstance(content, list) else [content]
        lines = [line for item in items for line in _result_lines(item)]
        if not lines:
            return ""
        text = f"[{data.get('type')}]\n" + "\n".join(lines)
    return text[:_MAX_SERVER_TOOL_TEXT]


def _result_lines(item) -> list[str]:
    """The links and output a server-side tool result item holds."""
    if not isinstance(item, dict):
        return []
    lines = []
    if item.get("url"):
        lines.append(f"- {item.get('title') or item['url']}: {item['url']}")
    lines.extend(
        f"{key}: {item[key]}"
        for key in ("stdout", "stderr")
        if isinstance(item.get(key), str) and item[key]
    )
    return lines
