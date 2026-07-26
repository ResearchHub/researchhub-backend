"""Unit tests for the Claude Platform on AWS provider adapter (no network)."""

from copy import deepcopy

from anthropic.types import Message as AnthropicMessage
from anthropic.types import (
    RedactedThinkingBlock,
    Usage,
)
from anthropic.types import (
    TextBlock as AnthropicTextBlock,
)
from anthropic.types import (
    ThinkingBlock as AnthropicThinkingBlock,
)
from anthropic.types import (
    ToolUseBlock as AnthropicToolUseBlock,
)
from django.test import SimpleTestCase, override_settings

from research_ai.services.agent.errors import ProviderError
from research_ai.services.agent.providers.claude_platform import ClaudePlatformProvider
from research_ai.services.agent.tools import Tool
from research_ai.services.agent.types import (
    Message,
    StopReason,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    TurnUsage,
)


class FakeMessages:
    """Returns queued Messages API responses; records the kwargs it was sent."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        return self._responses.pop(0)


class FakeAnthropicClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


def _build_response(content, *, stop_reason="end_turn", usage=None):
    return AnthropicMessage(
        id="msg_1",
        content=content,
        model="claude-opus-5",
        role="assistant",
        type="message",
        stop_reason=stop_reason,
        usage=usage or Usage(input_tokens=10, output_tokens=3),
    )


def _build_provider(responses=None, **kwargs):
    """Build a provider with a fake client so no AWS client is constructed."""
    return ClaudePlatformProvider(
        client=FakeAnthropicClient(responses or []),
        model_id=kwargs.pop("model_id", "claude-opus-5"),
    )


def _complete(provider, *, messages=None, rendered_tools=None, temperature=0.0):
    return provider.complete(
        system_prompt="sys",
        messages=messages or [Message(role="user", content=[TextBlock(text="hi")])],
        rendered_tools=rendered_tools if rendered_tools is not None else [],
        max_tokens=100,
        temperature=temperature,
    )


class RenderToolsTests(SimpleTestCase):
    def test_render_tools_produces_messages_api_shape(self):
        # Arrange
        provider = _build_provider()
        tool = Tool(
            name="search",
            description="search things",
            input_schema={"type": "object", "properties": {}},
            handler=lambda input: {},
        )

        # Act
        rendered = provider.render_tools([tool])

        # Assert
        self.assertEqual(
            rendered,
            [
                {
                    "name": "search",
                    "description": "search things",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ],
        )


class RenderMessagesTests(SimpleTestCase):
    def test_blocks_render_to_messages_api_wire_shapes(self):
        # Arrange
        provider = _build_provider()
        messages = [
            Message(role="user", content=[TextBlock(text="hi")]),
            Message(
                role="assistant",
                content=[
                    ThinkingBlock(
                        data={"type": "thinking", "thinking": "", "signature": "sig"}
                    ),
                    ToolUseBlock(id="t1", name="search", input={"q": 1}),
                ],
            ),
            Message(
                role="user",
                content=[
                    ToolResultBlock(
                        tool_use_id="t1", content={"ok": True}, is_error=False
                    ),
                    ToolResultBlock(
                        tool_use_id="t2", content={"error": "x"}, is_error=True
                    ),
                ],
            ),
        ]

        # Act
        rendered = provider._render_messages(messages)

        # Assert: text, thinking (verbatim), tool_use, and tool_result shapes.
        self.assertEqual(rendered[0]["content"][0], {"type": "text", "text": "hi"})
        self.assertEqual(
            rendered[1]["content"][0],
            {"type": "thinking", "thinking": "", "signature": "sig"},
        )
        self.assertEqual(
            rendered[1]["content"][1],
            {"type": "tool_use", "id": "t1", "name": "search", "input": {"q": 1}},
        )
        self.assertEqual(
            rendered[2]["content"][0],
            {
                "type": "tool_result",
                "tool_use_id": "t1",
                "content": '{"ok": true}',
            },
        )
        self.assertTrue(rendered[2]["content"][1]["is_error"])

    def test_tool_result_payload_survives_a_non_json_value(self):
        # Arrange: a stray non-JSON value must not take down the whole turn.
        provider = _build_provider()
        messages = [
            Message(
                role="user",
                content=[ToolResultBlock(tool_use_id="t1", content={"when": object()})],
            )
        ]

        # Act
        rendered = provider._render_messages(messages)

        # Assert
        self.assertIn("when", rendered[0]["content"][0]["content"])


class CompleteAndParseTests(SimpleTestCase):
    def test_complete_parses_text_tool_use_and_stop_reason(self):
        # Arrange
        response = _build_response(
            [
                AnthropicTextBlock(type="text", text="let me search"),
                AnthropicToolUseBlock(
                    type="tool_use", id="t1", name="search", input={"q": "jane"}
                ),
            ],
            stop_reason="tool_use",
        )
        provider = _build_provider([response])

        # Act
        turn = _complete(
            provider, rendered_tools=[{"name": "search", "input_schema": {}}]
        )

        # Assert
        self.assertEqual(turn.text, "let me search")
        self.assertEqual(len(turn.tool_calls), 1)
        self.assertEqual(turn.tool_calls[0].id, "t1")
        self.assertEqual(turn.tool_calls[0].input, {"q": "jane"})
        self.assertEqual(turn.stop_reason, StopReason.TOOL_USE)
        self.assertIn("tools", provider._client.messages.calls[0])

    def test_thinking_blocks_are_captured_verbatim_for_replay(self):
        # Arrange: signed reasoning blocks must survive the round trip intact.
        response = _build_response(
            [
                AnthropicThinkingBlock(
                    type="thinking", thinking="step one", signature="sig"
                ),
                RedactedThinkingBlock(type="redacted_thinking", data="opaque"),
                AnthropicTextBlock(type="text", text="done"),
            ]
        )
        provider = _build_provider([response])

        # Act
        turn = _complete(provider)

        # Assert
        self.assertEqual(
            [block.data for block in turn.thinking_blocks],
            [
                {"type": "thinking", "thinking": "step one", "signature": "sig"},
                {"type": "redacted_thinking", "data": "opaque"},
            ],
        )
        self.assertEqual(turn.text, "done")

    def test_adaptive_thinking_and_effort_are_sent_and_temperature_is_not(self):
        # Arrange: Opus 5 thinks by default and rejects sampling params.
        provider = _build_provider([_build_response([])])

        # Act
        _complete(provider, temperature=0.7)

        # Assert
        call = provider._client.messages.calls[0]
        self.assertEqual(call["thinking"], {"type": "adaptive"})
        self.assertEqual(call["output_config"], {"effort": "high"})
        self.assertNotIn("temperature", call)

    @override_settings(
        RESEARCH_AI_CLAUDE_PLATFORM_THINKING="",
        RESEARCH_AI_CLAUDE_PLATFORM_EFFORT="",
    )
    def test_thinking_off_forwards_temperature_for_a_sampling_model(self):
        # Arrange: with thinking omitted, a sampling-friendly model keeps it.
        provider = ClaudePlatformProvider(
            client=FakeAnthropicClient([_build_response([])]),
            model_id="claude-haiku-4-5",
        )

        # Act
        _complete(provider, temperature=0.7)

        # Assert
        call = provider._client.messages.calls[0]
        self.assertNotIn("thinking", call)
        self.assertNotIn("output_config", call)
        self.assertEqual(call["temperature"], 0.7)

    def test_prompt_caching_marks_system_and_the_last_message_block(self):
        # Arrange
        provider = _build_provider([_build_response([])])
        provider.prompt_caching = True

        # Act
        _complete(provider)

        # Assert: one breakpoint covers tools+system, one the conversation tail.
        call = provider._client.messages.calls[0]
        self.assertEqual(call["system"][-1]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(
            call["messages"][-1]["content"][-1]["cache_control"],
            {"type": "ephemeral"},
        )

    def test_prompt_caching_disabled_emits_no_breakpoints(self):
        # Arrange
        provider = _build_provider([_build_response([])])
        provider.prompt_caching = False

        # Act
        _complete(provider)

        # Assert
        call = provider._client.messages.calls[0]
        self.assertEqual(call["system"], [{"type": "text", "text": "sys"}])
        self.assertNotIn("cache_control", call["messages"][-1]["content"][-1])

    def test_complete_fills_usage_and_latency(self):
        # Arrange
        response = _build_response(
            [],
            usage=Usage(
                input_tokens=10,
                output_tokens=3,
                cache_read_input_tokens=5,
                cache_creation_input_tokens=2,
            ),
        )
        provider = _build_provider([response])

        # Act
        turn = _complete(provider)

        # Assert: normalized into the neutral per-turn metadata.
        self.assertEqual(
            turn.usage,
            TurnUsage(
                input_tokens=10,
                output_tokens=3,
                cache_read_tokens=5,
                cache_write_tokens=2,
            ),
        )
        self.assertIsNotNone(turn.latency_ms)

    def test_refusal_stop_reason_maps_to_content_filtered(self):
        # Arrange: a policy decline is a 200 with empty content, not an error.
        provider = _build_provider([_build_response([], stop_reason="refusal")])

        # Act
        turn = _complete(provider)

        # Assert: the loop reports an incomplete turn rather than an end_turn.
        self.assertEqual(turn.stop_reason, StopReason.CONTENT_FILTERED)

    def test_unknown_stop_reason_maps_to_other(self):
        # Arrange
        provider = _build_provider([_build_response([], stop_reason="pause_turn")])

        # Act
        turn = _complete(provider)

        # Assert
        self.assertEqual(turn.stop_reason, StopReason.OTHER)

    @override_settings(ANTHROPIC_AWS_WORKSPACE_ID="")
    def test_unconfigured_platform_builds_but_fails_on_complete(self):
        # Arrange: constructing a provider must not need credentials -- the
        # registry and the judge roster build one just to report its model.
        provider = ClaudePlatformProvider(model_id="claude-opus-5")

        # Act / Assert: the misconfiguration surfaces at call time, named.
        self.assertIsNone(provider._client)
        with self.assertRaisesRegex(ProviderError, "ANTHROPIC_AWS_WORKSPACE_ID"):
            _complete(provider)

    def test_client_exception_raises_provider_error(self):
        # Arrange: the SDK dies (throttling, network, SigV4 rejection).
        class ExplodingMessages:
            def create(self, **kwargs):
                raise ValueError("overloaded_error")

        class ExplodingClient:
            messages = ExplodingMessages()

        provider = ClaudePlatformProvider(
            client=ExplodingClient(), model_id="claude-opus-5"
        )

        # Act / Assert: typed, chained to the original client error.
        with self.assertRaisesRegex(ProviderError, "overloaded_error") as ctx:
            _complete(provider)
        self.assertIsInstance(ctx.exception.__cause__, ValueError)


class ModelConfigTests(SimpleTestCase):
    def test_default_model_is_opus_5(self):
        # Arrange / Act
        provider = ClaudePlatformProvider(client=FakeAnthropicClient([]))

        # Assert: the bare first-party id -- Claude Platform takes no prefix.
        self.assertEqual(provider.model_id, "claude-opus-5")

    @override_settings(RESEARCH_AI_CLAUDE_PLATFORM_MODEL_ID="claude-sonnet-5")
    def test_model_id_setting_overrides_the_default(self):
        # Arrange / Act
        provider = ClaudePlatformProvider(client=FakeAnthropicClient([]))

        # Assert
        self.assertEqual(provider.model_id, "claude-sonnet-5")
