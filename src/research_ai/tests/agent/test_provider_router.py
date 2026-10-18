"""Unit tests for the refusal-fallback router (no network)."""

from django.test import SimpleTestCase

from research_ai.services.agent.providers.base import LLMProvider
from research_ai.services.agent.providers.router import STATE_KEY, RoutedProvider
from research_ai.services.agent.tools import Tool
from research_ai.services.agent.types import (
    AssistantTurn,
    Message,
    ServerToolBlock,
    StopReason,
    StreamReset,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    TurnUsage,
)

PRIMARY = "claude_platform:claude-opus-5-5"
FALLBACK = "openrouter:moonshotai/kimi-k3"


class ScriptedProvider(LLMProvider):
    """Returns queued turns, reporting each one's usage; records its requests."""

    def __init__(self, turns=(), *, native_tool_names=frozenset()):
        self.turns = list(turns)
        self.requests = []
        self._native_tool_names = native_tool_names

    @property
    def native_tool_names(self):
        return self._native_tool_names

    def render_tools(self, tools):
        return [tool.name for tool in tools]

    def complete(self, *, messages, rendered_tools, on_usage=None, **kwargs):
        self.requests.append({"messages": messages, "tools": rendered_tools})
        turn = self.turns.pop(0)
        if on_usage is not None and turn.usage is not None:
            on_usage(turn.usage)
        return turn


def _turn(stop_reason, text="", *, usage=None):
    return AssistantTurn(
        text_blocks=[TextBlock(text=text)] if text else [],
        tool_calls=[],
        stop_reason=stop_reason,
        usage=usage,
    )


def _refusal(usage=None):
    return _turn(StopReason.CONTENT_FILTERED, usage=usage)


def _router(primary, fallback, *, fallback_ref=FALLBACK):
    return RoutedProvider(
        primary_ref=PRIMARY,
        primary=primary,
        fallback_ref=fallback_ref,
        build={FALLBACK: fallback}.__getitem__,
    )


def _user(text="hi"):
    return Message(role="user", content=[TextBlock(text=text)])


def _from_fallback(*content):
    return Message(
        role="assistant",
        content=list(content),
        provider_state={STATE_KEY: {"model": FALLBACK}},
    )


def _complete(router, messages, *, tools=(), events=None, usages=None, retries=None):
    return router.complete_with_events(
        system_prompt="sys",
        messages=messages,
        rendered_tools=router.render_tools(list(tools)),
        max_tokens=None,
        temperature=0.0,
        on_event=None if events is None else events.append,
        before_retry=None if retries is None else lambda: retries.append(True),
        on_usage=None if usages is None else usages.append,
    )


class RoutedProviderTests(SimpleTestCase):
    def test_refused_turn_is_answered_by_the_fallback(self):
        # Arrange
        primary = ScriptedProvider([_refusal()])
        fallback = ScriptedProvider([_turn(StopReason.END_TURN, "answer")])
        events, retries = [], []

        # Act
        turn = _complete(
            _router(primary, fallback), [_user()], events=events, retries=retries
        )

        # Assert
        self.assertEqual(turn.text, "answer")
        self.assertEqual(turn.provider_state, {STATE_KEY: {"model": FALLBACK}})
        self.assertEqual(events, [StreamReset()])
        self.assertEqual(retries, [True])

    def test_each_response_is_charged_to_the_model_that_wrote_it(self):
        # Arrange
        primary = ScriptedProvider([_refusal(usage=TurnUsage(input_tokens=10))])
        fallback = ScriptedProvider(
            [_turn(StopReason.END_TURN, "ok", usage=TurnUsage(input_tokens=20))]
        )
        usages = []

        # Act
        _complete(_router(primary, fallback), [_user()], usages=usages)

        # Assert: unnamed usage belongs to the run's own model.
        self.assertEqual(
            usages,
            [
                TurnUsage(input_tokens=10),
                TurnUsage(input_tokens=20, model_ref=FALLBACK),
            ],
        )

    def test_conversation_the_fallback_answered_stays_on_it(self):
        # Arrange
        primary = ScriptedProvider()
        fallback = ScriptedProvider([_turn(StopReason.END_TURN, "again")])
        history = [_user("first"), _from_fallback(TextBlock(text="sure")), _user()]

        # Act
        turn = _complete(_router(primary, fallback, fallback_ref=None), history)

        # Assert: even with new fallbacks switched off.
        self.assertEqual(turn.text, "again")
        self.assertEqual(primary.requests, [])

    def test_refusal_on_the_fallback_is_final(self):
        # Arrange
        primary = ScriptedProvider([_refusal()])
        fallback = ScriptedProvider([_refusal()])

        # Act
        turn = _complete(_router(primary, fallback), [_user()])

        # Assert: kept on the fallback, so the next message starts there.
        self.assertEqual(turn.stop_reason, StopReason.CONTENT_FILTERED)
        self.assertEqual(turn.provider_state, {STATE_KEY: {"model": FALLBACK}})

    def test_refusal_without_a_fallback_is_returned(self):
        # Arrange
        primary = ScriptedProvider([_refusal()])

        # Act
        turn = _complete(_router(primary, None, fallback_ref=None), [_user()])

        # Assert
        self.assertEqual(turn.stop_reason, StopReason.CONTENT_FILTERED)
        self.assertEqual(turn.provider_state, {})

    def test_turns_by_another_model_keep_only_text_and_tool_calls(self):
        # Arrange
        claude_turn = Message(
            role="assistant",
            content=[
                ThinkingBlock(data={"type": "thinking", "signature": "sig"}),
                ServerToolBlock(
                    data={
                        "type": "server_tool_use",
                        "name": "web_search",
                        "input": {"query": "prions"},
                    }
                ),
                ServerToolBlock(
                    data={
                        "type": "web_search_tool_result",
                        "content": [
                            {
                                "url": "https://a.test",
                                "title": "A",
                                "encrypted_content": "x",
                            }
                        ],
                    }
                ),
                TextBlock(text="Found it.", data={"citations": ["opaque"]}),
                ToolUseBlock(
                    id="toolu_1", name="read_note", input={}, data={"caller": "x"}
                ),
            ],
            provider_state={"anthropic": {"container": {"id": "c1"}}},
        )
        result = Message(
            role="user", content=[ToolResultBlock(tool_use_id="toolu_1", content={})]
        )
        kimi_turn = _from_fallback(
            ThinkingBlock(data={"type": "reasoning.text"}), TextBlock(text="Done.")
        )
        primary = ScriptedProvider()
        fallback = ScriptedProvider([_turn(StopReason.END_TURN, "ok")])

        # Act
        _complete(
            _router(primary, fallback),
            [_user(), claude_turn, result, kimi_turn, _user("next")],
        )

        # Assert: the fallback's own turn is replayed as written.
        sent = fallback.requests[0]["messages"]
        self.assertEqual(
            sent[1],
            Message(
                role="assistant",
                content=[
                    TextBlock(text='[web_search call: {"query": "prions"}]'),
                    TextBlock(text="[web_search_tool_result]\n- A: https://a.test"),
                    TextBlock(text="Found it."),
                    ToolUseBlock(id="toolu_1", name="read_note", input={}),
                ],
            ),
        )
        self.assertEqual(sent[2], result)
        self.assertEqual(sent[3], kimi_turn)

    def test_refused_turns_are_left_out_of_requests(self):
        # Arrange
        primary = ScriptedProvider([_turn(StopReason.END_TURN, "ok")])
        history = [_user("refused"), Message(role="assistant", content=[]), _user()]

        # Act
        _complete(_router(primary, None, fallback_ref=None), history)

        # Assert
        self.assertEqual(primary.requests[0]["messages"], [history[0], history[2]])

    def test_each_model_gets_the_local_tools_it_does_not_run_itself(self):
        # Arrange
        tools = [
            Tool("web_search", "search the web", {"type": "object"}, dict),
            Tool("read_note", "read the note", {"type": "object"}, dict),
        ]
        primary = ScriptedProvider(
            [_refusal()], native_tool_names=frozenset({"web_search"})
        )
        fallback = ScriptedProvider([_turn(StopReason.END_TURN, "ok")])
        router = _router(primary, fallback)

        # Act
        _complete(router, [_user()], tools=tools)

        # Assert: the toolset is composed with the local tool kept.
        self.assertEqual(router.native_tool_names, frozenset())
        self.assertEqual(primary.requests[0]["tools"], ["read_note"])
        self.assertEqual(fallback.requests[0]["tools"], ["web_search", "read_note"])
