"""Unit tests for the OpenRouter Chat Completions provider adapter (no network)."""

import json
from copy import deepcopy
from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from research_ai.services.agent.errors import ProviderError
from research_ai.services.agent.providers import openrouter
from research_ai.services.agent.providers.openrouter import OpenRouterProvider
from research_ai.services.agent.tools import Tool
from research_ai.services.agent.types import (
    Message,
    StopReason,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)


class FakeChatCompletionsClient:
    """Returns queued Chat Completions responses; records the kwargs sent."""

    def __init__(self, responses):
        completions = SimpleNamespace(create=self._create)
        self.chat = SimpleNamespace(completions=completions)
        self._responses = list(responses)
        self.calls = []

    def _create(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        return self._responses.pop(0)


def _response(
    *,
    content=None,
    tool_calls=None,
    finish_reason="stop",
    usage=None,
):
    """Build a minimal SDK-shaped Chat Completions response object."""
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=usage)


def _tool_call(call_id="call-1", name="search", arguments='{"q": 1}'):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _build_provider(responses=None, model_id="test-model", **kwargs):
    """Build an OpenRouterProvider with a fake client so no HTTP client exists."""
    return OpenRouterProvider(
        client=FakeChatCompletionsClient(responses or []),
        model_id=model_id,
        **kwargs,
    )


def _complete(provider, messages=None, rendered_tools=None):
    return provider.complete(
        system_prompt="sys",
        messages=messages or [Message(role="user", content=[TextBlock(text="hi")])],
        rendered_tools=rendered_tools or [],
        max_tokens=100,
        temperature=0.5,
    )


class RenderToolsTests(SimpleTestCase):
    def test_render_tools_produces_function_tool_shape(self):
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
                    "type": "function",
                    "function": {
                        "name": "search",
                        "description": "search things",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        )


class RenderMessagesTests(SimpleTestCase):
    def test_blocks_render_to_chat_completions_wire_shapes(self):
        # Arrange
        provider = _build_provider([_response(content="ok")])
        messages = [
            Message(role="user", content=[TextBlock(text="hi")]),
            Message(
                role="assistant",
                content=[
                    TextBlock(text="calling"),
                    ToolUseBlock(id="t1", name="search", input={"q": 1}),
                ],
            ),
            Message(
                role="user",
                content=[ToolResultBlock(tool_use_id="t1", content={"hits": 2})],
            ),
        ]

        # Act
        _complete(provider, messages=messages)

        # Assert
        sent = provider._client.calls[0]["messages"]
        self.assertEqual(sent[0], {"role": "system", "content": "sys"})
        self.assertEqual(sent[1], {"role": "user", "content": "hi"})
        self.assertEqual(sent[2]["role"], "assistant")
        self.assertEqual(sent[2]["content"], "calling")
        self.assertEqual(
            sent[2]["tool_calls"],
            [
                {
                    "id": "t1",
                    "type": "function",
                    "function": {"name": "search", "arguments": '{"q": 1}'},
                }
            ],
        )
        self.assertEqual(
            sent[3],
            {"role": "tool", "tool_call_id": "t1", "content": '{"hits": 2}'},
        )

    def test_tool_results_precede_user_text_in_the_same_message(self):
        # Arrange
        provider = _build_provider([_response(content="ok")])
        messages = [
            Message(
                role="user",
                content=[
                    TextBlock(text="feedback"),
                    ToolResultBlock(tool_use_id="t1", content={"ok": True}),
                ],
            ),
        ]

        # Act
        _complete(provider, messages=messages)

        # Assert: the tool message must directly follow the assistant turn, so
        # it renders before the plain-text user message regardless of block order.
        sent = provider._client.calls[0]["messages"]
        self.assertEqual(sent[1]["role"], "tool")
        self.assertEqual(sent[2], {"role": "user", "content": "feedback"})

    def test_assistant_tool_only_turn_renders_null_content(self):
        # Arrange
        provider = _build_provider([_response(content="ok")])
        messages = [
            Message(
                role="assistant",
                content=[ToolUseBlock(id="t1", name="search", input={})],
            ),
            Message(
                role="user",
                content=[ToolResultBlock(tool_use_id="t1", content={})],
            ),
        ]

        # Act
        _complete(provider, messages=messages)

        # Assert
        sent = provider._client.calls[0]["messages"]
        self.assertIsNone(sent[1]["content"])


class CompleteRequestTests(SimpleTestCase):
    def test_tools_and_sampling_params_are_sent(self):
        # Arrange
        provider = _build_provider([_response(content="ok")], effort="low")
        rendered_tools = [{"type": "function", "function": {"name": "search"}}]

        # Act
        _complete(provider, rendered_tools=rendered_tools)

        # Assert
        kwargs = provider._client.calls[0]
        self.assertEqual(kwargs["model"], "test-model")
        self.assertEqual(kwargs["max_tokens"], 100)
        self.assertEqual(kwargs["temperature"], 0.5)
        self.assertEqual(kwargs["tools"], rendered_tools)
        self.assertEqual(kwargs["extra_body"], {"reasoning": {"effort": "low"}})

    def test_effort_can_be_omitted_for_incompatible_models(self):
        # Arrange
        provider = _build_provider([_response(content="ok")])

        # Act
        _complete(provider)

        # Assert
        self.assertNotIn("extra_body", provider._client.calls[0])

    def test_default_effort_is_sent_for_a_capable_model(self):
        # Arrange
        provider = _build_provider(
            [_response(content="ok")], model_id="google/gemini-3.1-pro-preview"
        )

        # Act
        _complete(provider)

        # Assert
        self.assertEqual(
            provider._client.calls[0]["extra_body"],
            {"reasoning": {"effort": "low"}},
        )

    def test_frontend_generation_options_are_sent_as_reasoning(self):
        # Arrange
        client = FakeChatCompletionsClient([_response(content="ok")])
        provider = OpenRouterProvider(
            client=client,
            model_id="openai/gpt-5.6-sol",
            effort="high",
            thinking="adaptive",
        )

        # Act
        _complete(provider)

        # Assert
        self.assertEqual(
            client.calls[0]["extra_body"],
            {"reasoning": {"enabled": True, "effort": "high"}},
        )

    def test_disabled_thinking_suppresses_effort(self):
        # Arrange
        client = FakeChatCompletionsClient([_response(content="ok")])
        provider = OpenRouterProvider(
            client=client,
            model_id="openai/gpt-5.6-sol",
            effort="high",
            thinking="disabled",
        )

        # Act
        _complete(provider)

        # Assert
        self.assertEqual(
            client.calls[0]["extra_body"], {"reasoning": {"enabled": False}}
        )

    def test_none_max_tokens_resolves_to_the_adapter_output_ceiling(self):
        # Arrange
        provider = _build_provider([_response(content="ok")])

        # Act
        provider.complete(
            system_prompt="sys",
            messages=[Message(role="user", content=[TextBlock(text="hi")])],
            rendered_tools=[],
            max_tokens=None,
            temperature=0.5,
        )

        # Assert
        self.assertEqual(
            provider._client.calls[0]["max_tokens"], openrouter.MAX_OUTPUT_TOKENS
        )

    def test_no_tools_key_when_toolset_is_empty(self):
        # Arrange
        provider = _build_provider([_response(content="ok")])

        # Act
        _complete(provider, rendered_tools=[])

        # Assert
        self.assertNotIn("tools", provider._client.calls[0])

    def test_sampling_params_omitted_for_models_that_reject_them(self):
        # Arrange
        provider = _build_provider(
            [_response(content="ok")], model_id="anthropic/claude-opus-4.8"
        )

        # Act
        _complete(provider)

        # Assert
        self.assertNotIn("temperature", provider._client.calls[0])


class ParseTurnTests(SimpleTestCase):
    def test_text_turn_parses_to_end_turn(self):
        # Arrange
        provider = _build_provider([_response(content="hello", finish_reason="stop")])

        # Act
        turn = _complete(provider)

        # Assert
        self.assertEqual(turn.text, "hello")
        self.assertEqual(turn.tool_calls, [])
        self.assertEqual(turn.stop_reason, StopReason.END_TURN)

    def test_tool_call_turn_parses_arguments_json(self):
        # Arrange
        provider = _build_provider(
            [
                _response(
                    tool_calls=[_tool_call(arguments='{"q": "x"}')],
                    finish_reason="tool_calls",
                )
            ]
        )

        # Act
        turn = _complete(provider)

        # Assert
        self.assertEqual(turn.stop_reason, StopReason.TOOL_USE)
        self.assertEqual(
            turn.tool_calls,
            [ToolUseBlock(id="call-1", name="search", input={"q": "x"})],
        )

    def test_malformed_arguments_fall_back_to_empty_input(self):
        # Arrange
        provider = _build_provider(
            [
                _response(
                    tool_calls=[_tool_call(arguments="not json")],
                    finish_reason="tool_calls",
                )
            ]
        )

        # Act
        turn = _complete(provider)

        # Assert
        self.assertEqual(turn.tool_calls[0].input, {})

    def test_stop_finish_reason_with_tool_calls_still_reports_tool_use(self):
        # Arrange
        provider = _build_provider(
            [_response(tool_calls=[_tool_call()], finish_reason="stop")]
        )

        # Act
        turn = _complete(provider)

        # Assert
        self.assertEqual(turn.stop_reason, StopReason.TOOL_USE)

    def test_length_finish_reason_maps_to_max_tokens(self):
        # Arrange
        provider = _build_provider([_response(content="cut", finish_reason="length")])

        # Act
        turn = _complete(provider)

        # Assert
        self.assertEqual(turn.stop_reason, StopReason.MAX_TOKENS)

    def test_usage_parses_including_cached_tokens(self):
        # Arrange
        usage = SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=20,
            prompt_tokens_details=SimpleNamespace(cached_tokens=80),
        )
        provider = _build_provider([_response(content="ok", usage=usage)])

        # Act
        turn = _complete(provider)

        # Assert
        self.assertEqual(turn.usage.input_tokens, 100)
        self.assertEqual(turn.usage.output_tokens, 20)
        self.assertEqual(turn.usage.cache_read_tokens, 80)

    def test_reasoning_details_are_preserved_for_replay(self):
        # Arrange
        detail = {
            "type": "reasoning.encrypted",
            "id": "reason-1",
            "data": "signed-payload",
            "format": "anthropic-claude-v1",
        }
        response = _response(content=None, tool_calls=[_tool_call()])
        response.choices[0].message.reasoning_details = [detail]
        provider = _build_provider([response])

        # Act
        turn = _complete(provider)

        # Assert
        self.assertEqual(turn.thinking_blocks, [ThinkingBlock(data=detail)])
        self.assertEqual(turn.content_blocks[0], ThinkingBlock(data=detail))

    def test_reasoning_details_are_replayed_on_the_next_request(self):
        # Arrange
        detail = {
            "type": "reasoning.encrypted",
            "id": "reason-1",
            "data": "signed-payload",
            "format": "anthropic-claude-v1",
        }
        provider = _build_provider([_response(content="ok")])
        messages = [
            Message(
                role="assistant",
                content=[
                    ThinkingBlock(data=detail),
                    ToolUseBlock(id="t1", name="search", input={}),
                ],
            ),
            Message(
                role="user",
                content=[ToolResultBlock(tool_use_id="t1", content={})],
            ),
        ]

        # Act
        _complete(provider, messages=messages)

        # Assert
        assistant = provider._client.calls[0]["messages"][1]
        self.assertEqual(assistant["reasoning_details"], [detail])

    def test_missing_message_raises_provider_error(self):
        # Arrange
        provider = _build_provider([SimpleNamespace(choices=[], usage=None)])

        # Act / Assert
        with self.assertRaises(ProviderError):
            _complete(provider)


class ErrorTests(SimpleTestCase):
    @override_settings(OPENROUTER_API_KEY="")
    def test_missing_api_key_raises_provider_error_on_complete(self):
        # Arrange
        provider = OpenRouterProvider(model_id="test-model")

        # Act / Assert
        with self.assertRaises(ProviderError):
            _complete(provider)

    def test_transport_failure_wraps_in_provider_error(self):
        # Arrange
        class ExplodingClient:
            def __init__(self):
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(create=self._create)
                )

            def _create(self, **kwargs):
                raise RuntimeError("boom")

        provider = OpenRouterProvider(client=ExplodingClient(), model_id="test-model")

        # Act / Assert
        with self.assertRaises(ProviderError):
            _complete(provider)


class DefaultsTests(SimpleTestCase):
    def test_model_id_defaults_to_opus_5(self):
        # Arrange / Act
        provider = _build_provider(model_id=None)

        # Assert
        self.assertEqual(provider.model_id, "anthropic/claude-opus-5")

    def test_round_trip_arguments_encoding(self):
        # Arrange: an assistant tool call rendered then a result echoing its id.
        provider = _build_provider([_response(content="ok")])
        tool_input = {"query": "protein folding", "limit": 3}
        messages = [
            Message(
                role="assistant",
                content=[ToolUseBlock(id="t9", name="search", input=tool_input)],
            ),
            Message(
                role="user",
                content=[ToolResultBlock(tool_use_id="t9", content={"n": 1})],
            ),
        ]

        # Act
        _complete(provider, messages=messages)

        # Assert: arguments JSON round-trips and the result keys to the call id.
        sent = provider._client.calls[0]["messages"]
        arguments = sent[1]["tool_calls"][0]["function"]["arguments"]
        self.assertEqual(json.loads(arguments), tool_input)
        self.assertEqual(sent[2]["tool_call_id"], "t9")
