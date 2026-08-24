"""Unit tests for the Claude Platform on AWS provider adapter (no network)."""

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

from anthropic.types import (
    CodeExecutionToolResultBlock,
    Container,
    EncryptedCodeExecutionResultBlock,
    RawMessageDeltaEvent,
    RedactedThinkingBlock,
    ServerToolUseBlock,
    Usage,
    WebSearchResultBlock,
    WebSearchToolResultBlock,
)
from anthropic.types import Message as AnthropicMessage
from anthropic.types import (
    TextBlock as AnthropicTextBlock,
)
from anthropic.types import (
    ThinkingBlock as AnthropicThinkingBlock,
)
from anthropic.types import (
    ToolUseBlock as AnthropicToolUseBlock,
)
from anthropic.types.refusal_stop_details import RefusalStopDetails
from django.test import SimpleTestCase, override_settings

from research_ai.services.agent.errors import ProviderError
from research_ai.services.agent.providers import claude_platform
from research_ai.services.agent.providers.claude_platform import ClaudePlatformProvider
from research_ai.services.agent.tools import Tool
from research_ai.services.agent.types import (
    Message,
    ServerToolBlock,
    StopReason,
    StreamReset,
    TextBlock,
    TextStreamDelta,
    ThinkingBlock,
    ThinkingStreamDelta,
    ToolInputStreamDelta,
    ToolResultBlock,
    ToolUseBlock,
    ToolUseStreamStart,
    TurnUsage,
)


class _FakeStream:
    """Stands in for the SDK's ``MessageStreamManager`` context manager."""

    def __init__(self, response, events=()):
        self._response = response
        self._events = list(events)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def __iter__(self):
        return iter(self._events)

    def get_final_message(self):
        return self._response


class FakeMessages:
    """Returns queued Messages API responses; records the kwargs it was sent."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        response = self._responses.pop(0)
        if getattr(response, "container", None) is None:
            return _FakeStream(response)
        # Faithful to the SDK: the container arrives on ``message_delta`` and
        # is never accumulated onto the final message.
        return _FakeStream(
            response.model_copy(update={"container": None}),
            [_build_container_delta(response.container, response.stop_reason)],
        )


class FakeAnthropicClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


def _build_response(
    content,
    *,
    stop_reason="end_turn",
    usage=None,
    container=None,
    stop_details=None,
):
    return AnthropicMessage(
        id="msg_1",
        container=container,
        content=content,
        model="claude-opus-5",
        role="assistant",
        type="message",
        stop_reason=stop_reason,
        stop_details=stop_details,
        usage=usage or Usage(input_tokens=10, output_tokens=3),
    )


def _build_container_delta(container, stop_reason="tool_use"):
    """The ``message_delta`` disclosing a container, in the SDK's wire shape.

    Deserialized rather than constructed: the container is a field of the
    event's ``delta``, and the SDK's models accept undeclared top-level keys.
    """
    return RawMessageDeltaEvent.model_validate(
        {
            "type": "message_delta",
            "delta": {
                "container": container.model_dump(mode="json"),
                "stop_reason": stop_reason,
                "stop_sequence": None,
            },
            "usage": {"output_tokens": 3},
        }
    )


def _build_server_search_blocks(query="llipta ash"):
    """One server-side search: the model's request and the injected result."""
    return [
        ServerToolUseBlock(
            id="srvtoolu_1",
            name="web_search",
            input={"query": query},
            type="server_tool_use",
        ),
        WebSearchToolResultBlock(
            tool_use_id="srvtoolu_1",
            type="web_search_tool_result",
            content=[
                WebSearchResultBlock(
                    type="web_search_result",
                    title="Andean plant ash",
                    url="https://example.org/llipta",
                    encrypted_content="enc",
                )
            ],
        ),
    ]


def _build_provider(responses=None, **kwargs):
    """Build a provider with a fake client so no AWS client is constructed."""
    return ClaudePlatformProvider(
        client=FakeAnthropicClient(responses or []),
        model_id=kwargs.pop("model_id", "claude-opus-5"),
        web_search=kwargs.pop("web_search", False),
    )


def _complete(
    provider,
    *,
    messages=None,
    rendered_tools=None,
    temperature=0.0,
    before_retry=None,
):
    return provider.complete(
        system_prompt="sys",
        messages=messages or [Message(role="user", content=[TextBlock(text="hi")])],
        rendered_tools=rendered_tools if rendered_tools is not None else [],
        max_tokens=100,
        temperature=temperature,
        before_retry=before_retry,
    )


class RenderToolsTests(SimpleTestCase):
    def test_render_tools_produces_messages_api_shape(self):
        # Arrange
        provider = _build_provider(web_search=True)
        tool = Tool(
            name="search",
            description="search things",
            input_schema={"type": "object", "properties": {}},
            handler=lambda input: {},
        )

        # Act
        rendered = provider.render_tools([tool])

        # Assert: the caller's tools, then the server-side ones the provider
        # declares itself.
        self.assertEqual(
            rendered,
            [
                {
                    "name": "search",
                    "description": "search things",
                    "input_schema": {"type": "object", "properties": {}},
                },
                {
                    "type": claude_platform.WEB_SEARCH_TOOL_TYPE,
                    "name": "web_search",
                    "max_uses": claude_platform.WEB_SEARCH_MAX_USES,
                },
            ],
        )

    def test_web_search_off_renders_only_the_callers_tools(self):
        # Arrange: native search is opt-in, so unrelated agents do not receive it.
        provider = _build_provider()
        tool = Tool(
            name="search",
            description="search things",
            input_schema={"type": "object", "properties": {}},
            handler=lambda input: {},
        )

        # Act
        rendered = provider.render_tools([tool])

        # Assert: nothing appended, and the name is left for a local tool.
        self.assertEqual([t["name"] for t in rendered], ["search"])
        self.assertEqual(provider.native_tool_names, frozenset())


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

    def test_non_json_tool_result_raises_provider_error(self):
        # Arrange: directly constructed invalid messages fail at this boundary.
        provider = _build_provider()
        messages = [
            Message(
                role="user",
                content=[ToolResultBlock(tool_use_id="t1", content={"when": object()})],
            )
        ]

        # Act / Assert
        with self.assertRaisesRegex(ProviderError, "not valid JSON"):
            provider._render_messages(messages)


class CompleteAndParseTests(SimpleTestCase):
    def test_reports_text_and_readable_thinking_deltas_in_order(self):
        # Arrange
        response = _build_response([AnthropicTextBlock(type="text", text="answer")])
        sdk_events = [
            SimpleNamespace(
                type="content_block_delta",
                index=0,
                delta=SimpleNamespace(type="thinking_delta", thinking="plan "),
            ),
            SimpleNamespace(
                type="content_block_delta",
                index=1,
                delta=SimpleNamespace(type="text_delta", text="answer"),
            ),
            # Signatures are replay state, not user-visible stream content.
            SimpleNamespace(
                type="content_block_delta",
                index=0,
                delta=SimpleNamespace(type="signature_delta", signature="secret"),
            ),
        ]

        class Messages:
            def stream(self, **_kwargs):
                return _FakeStream(response, sdk_events)

        provider = ClaudePlatformProvider(
            client=SimpleNamespace(messages=Messages()), model_id="claude-opus-5"
        )
        observed = []

        # Act
        turn = provider.complete_with_events(
            system_prompt="sys",
            messages=[Message(role="user", content=[TextBlock(text="hi")])],
            rendered_tools=[],
            max_tokens=100,
            temperature=0.0,
            on_event=observed.append,
        )

        # Assert
        self.assertEqual(turn.text, "answer")
        self.assertEqual(
            observed,
            [
                ThinkingStreamDelta(block_index=0, text="plan "),
                TextStreamDelta(block_index=1, text="answer"),
            ],
        )

    def test_reports_tool_use_starts_and_argument_deltas(self):
        # Arrange
        response = _build_response([AnthropicTextBlock(type="text", text="done")])
        sdk_events = [
            SimpleNamespace(
                type="content_block_start",
                index=0,
                content_block=SimpleNamespace(type="tool_use", name="edit_note"),
            ),
            SimpleNamespace(
                type="content_block_delta",
                index=0,
                delta=SimpleNamespace(type="input_json_delta", partial_json='{"no'),
            ),
            # Server-side tools announce themselves the same way.
            SimpleNamespace(
                type="content_block_start",
                index=1,
                content_block=SimpleNamespace(
                    type="server_tool_use", name="web_search"
                ),
            ),
            # Text blocks opening is not a tool event.
            SimpleNamespace(
                type="content_block_start",
                index=2,
                content_block=SimpleNamespace(type="text"),
            ),
        ]

        class Messages:
            def stream(self, **_kwargs):
                return _FakeStream(response, sdk_events)

        provider = ClaudePlatformProvider(
            client=SimpleNamespace(messages=Messages()), model_id="claude-opus-5"
        )
        observed = []

        # Act
        provider.complete_with_events(
            system_prompt="sys",
            messages=[Message(role="user", content=[TextBlock(text="hi")])],
            rendered_tools=[],
            max_tokens=100,
            temperature=0.0,
            on_event=observed.append,
        )

        # Assert
        self.assertEqual(
            observed,
            [
                ToolUseStreamStart(block_index=0, name="edit_note"),
                ToolInputStreamDelta(block_index=0, partial_json='{"no'),
                ToolUseStreamStart(block_index=1, name="web_search"),
            ],
        )

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
        self.assertEqual(
            call["thinking"], {"type": "adaptive", "display": "summarized"}
        )
        self.assertEqual(call["output_config"], {"effort": "low"})
        self.assertNotIn("temperature", call)

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

    def test_refusal_carries_the_classifier_category(self):
        # Arrange: a refused turn has no content, so its stop details are the
        # only thing that says which classifier declined it.
        provider = _build_provider(
            [
                _build_response(
                    [],
                    stop_reason="refusal",
                    stop_details=RefusalStopDetails(
                        type="refusal",
                        category="bio",
                        explanation="declined by policy",
                    ),
                )
            ]
        )

        # Act
        turn = _complete(provider)

        # Assert
        self.assertEqual(turn.stop_details["category"], "bio")
        self.assertEqual(turn.stop_details["explanation"], "declined by policy")

    def test_completed_turn_has_no_stop_details(self):
        # Arrange: stop details are populated for refusals only.
        provider = _build_provider(
            [_build_response([AnthropicTextBlock(type="text", text="done")])]
        )

        # Act
        turn = _complete(provider)

        # Assert
        self.assertIsNone(turn.stop_details)

    def test_unknown_stop_reason_maps_to_other(self):
        # Arrange: every stop reason the SDK knows today is mapped, so this
        # fallback is only reachable from one a newer API adds. Assigned past
        # the SDK's literal validation to stand in for that.
        response = _build_response([])
        response.stop_reason = "something_new_from_the_api"
        provider = _build_provider([response])

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
            def stream(self, **kwargs):
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

    def test_mid_stream_exception_raises_provider_error(self):
        # Arrange: the connection dies after the stream opened, while the turn
        # was still being emitted.
        class ExplodingStream:
            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

            def __iter__(self):
                raise ValueError("connection reset")

            def get_final_message(self):
                raise ValueError("connection reset")

        class ExplodingMessages:
            def stream(self, **kwargs):
                return ExplodingStream()

        class ExplodingClient:
            messages = ExplodingMessages()

        provider = ClaudePlatformProvider(
            client=ExplodingClient(), model_id="claude-opus-5"
        )

        # Act / Assert
        with self.assertRaisesRegex(ProviderError, "connection reset") as ctx:
            _complete(provider)
        self.assertIsInstance(ctx.exception.__cause__, ValueError)

    def test_none_max_tokens_resolves_to_the_model_output_ceiling(self):
        # Arrange
        provider = _build_provider([_build_response([])])

        # Act
        provider.complete(
            system_prompt="sys",
            messages=[Message(role="user", content=[TextBlock(text="hi")])],
            rendered_tools=[],
            max_tokens=None,
            temperature=0.0,
        )

        # Assert
        call = provider._client.messages.calls[0]
        self.assertEqual(call["max_tokens"], claude_platform.MAX_OUTPUT_TOKENS)

    def test_explicit_max_tokens_is_forwarded_unchanged(self):
        # Arrange: the _complete helper passes max_tokens=100.
        provider = _build_provider([_build_response([])])

        # Act
        _complete(provider)

        # Assert
        self.assertEqual(provider._client.messages.calls[0]["max_tokens"], 100)


class ServerSideToolTests(SimpleTestCase):
    """Web search runs inside the turn: the loop never dispatches it."""

    def test_logs_request_and_response_continuation_state(self):
        # Arrange: the outgoing history and incoming response both have a
        # code-generated client call and an unresolved server-tool span.
        code_caller = {
            "type": "code_execution_20260120",
            "tool_id": "srvtoolu_code",
        }
        initial = Message(role="user", content=[TextBlock(text="research")])
        assistant = Message(
            role="assistant",
            content=[
                ServerToolBlock(
                    data={
                        "type": "server_tool_use",
                        "id": "srvtoolu_request",
                        "name": "code_execution",
                        "input": {"code": "await search({})"},
                    }
                ),
                ToolUseBlock(
                    id="toolu_request",
                    name="search",
                    input={},
                    data={
                        "type": "tool_use",
                        "id": "toolu_request",
                        "name": "search",
                        "input": {},
                        "caller": code_caller,
                    },
                ),
            ],
            provider_state={
                "anthropic": {"container": {"id": "container_123"}},
            },
        )
        result = Message(
            role="user",
            content=[ToolResultBlock(tool_use_id="toolu_request", content={})],
        )
        response = _build_response(
            [
                ServerToolUseBlock(
                    id="srvtoolu_response",
                    name="code_execution",
                    input={"code": "await verify({})"},
                    type="server_tool_use",
                ),
                AnthropicToolUseBlock(
                    id="toolu_response",
                    name="verify",
                    input={},
                    caller=code_caller,
                    type="tool_use",
                ),
            ],
            stop_reason="tool_use",
            container=Container(
                id="container_456",
                expires_at=datetime(2099, 1, 1, tzinfo=UTC),
            ),
        )
        provider = _build_provider([response])

        # Act
        with self.assertLogs(
            "research_ai.services.agent.providers.claude_platform",
            level="INFO",
        ) as logs:
            _complete(provider, messages=[initial, assistant, result])

        # Assert
        output = "\n".join(logs.output)
        self.assertIn("request_container_present=True", output)
        self.assertIn("response_container_present=True", output)
        self.assertEqual(output.count("pending_programmatic_tool_calls=1"), 2)
        self.assertEqual(output.count("pending_server_tool_spans=1"), 2)
        self.assertIn("stop_reason=tool_use", output)

    def test_server_search_blocks_are_parsed_and_kept_in_order(self):
        # Arrange: a turn that thinks, searches server-side, then answers.
        response = _build_response(
            [
                AnthropicThinkingBlock(type="thinking", thinking="", signature="sig"),
                *_build_server_search_blocks(),
                AnthropicTextBlock(type="text", text="found it"),
            ]
        )
        provider = _build_provider([response])

        # Act
        turn = _complete(provider)

        # Assert: both halves of the search are carried as opaque server-tool
        # blocks, in the provider's original order -- a result must stay
        # immediately after its request -- and none of it is a call to dispatch.
        self.assertEqual(
            [type(block).__name__ for block in turn.replay_content],
            ["ThinkingBlock", "ServerToolBlock", "ServerToolBlock", "TextBlock"],
        )
        self.assertEqual(turn.replay_content[1].data["name"], "web_search")
        self.assertEqual(turn.text, "found it")
        self.assertEqual(turn.tool_calls, [])

    def test_server_tool_blocks_replay_verbatim_and_still_paired(self):
        # Arrange: parse a searching turn, then send it back as history.
        provider = _build_provider([_build_response(_build_server_search_blocks())])
        turn = _complete(provider)

        # Act
        rendered = provider._render_messages(
            [Message(role="assistant", content=turn.replay_content)]
        )

        # Assert: unedited wire shapes, request then result, ids still matching.
        request, result = rendered[0]["content"]
        self.assertEqual(request["type"], "server_tool_use")
        self.assertEqual(result["type"], "web_search_tool_result")
        self.assertEqual(result["tool_use_id"], request["id"])

    def test_code_execution_result_replays_with_encrypted_output(self):
        # Arrange: web search may invoke provider-managed code execution and
        # return its encrypted output as another assistant response block.
        request = ServerToolUseBlock(
            id="srvtoolu_2",
            name="code_execution",
            input={"code": "print('done')"},
            type="server_tool_use",
        )
        result = CodeExecutionToolResultBlock(
            type="code_execution_tool_result",
            tool_use_id="srvtoolu_2",
            content=EncryptedCodeExecutionResultBlock(
                type="encrypted_code_execution_result",
                content=[],
                encrypted_stdout="enc-stdout",
                return_code=0,
                stderr="",
            ),
        )
        provider = _build_provider([_build_response([request, result])])
        turn = _complete(provider)

        # Act
        rendered = provider._render_messages(
            [Message(role="assistant", content=turn.replay_content)]
        )

        # Assert: both blocks remain paired and the encrypted replay state is
        # preserved exactly instead of being rejected or reconstructed.
        replayed_request, replayed_result = rendered[0]["content"]
        self.assertEqual(replayed_result, result.model_dump(mode="json"))
        self.assertEqual(replayed_result["tool_use_id"], replayed_request["id"])
        self.assertEqual(
            replayed_result["content"]["encrypted_stdout"],
            "enc-stdout",
        )

    def test_container_disclosed_only_by_a_stream_event_is_recorded(self):
        # Arrange: Anthropic reports the container on ``message_delta``, which
        # the SDK never accumulates onto the final message -- reading the final
        # message alone loses the id every later request needs.
        container = Container(
            id="container_123",
            expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        )
        delta = _build_container_delta(container)

        class DeltaOnlyMessages:
            def stream(self, **kwargs):
                return _FakeStream(_build_response([], stop_reason="tool_use"), [delta])

        class DeltaOnlyClient:
            messages = DeltaOnlyMessages()

        provider = ClaudePlatformProvider(
            client=DeltaOnlyClient(), model_id="claude-opus-5"
        )

        # Act
        turn = _complete(provider)

        # Assert
        self.assertEqual(
            turn.provider_state["anthropic"]["container"]["id"],
            "container_123",
        )

    def test_code_execution_container_and_tool_caller_replay_on_followup(self):
        # Arrange: code execution paused while a client tool runs. Anthropic
        # requires both its top-level container id and the tool call's caller
        # metadata when the result is sent back.
        code_execution = ServerToolUseBlock(
            id="srvtoolu_code",
            name="code_execution",
            input={"code": "await search({'q': 'llipta'})"},
            type="server_tool_use",
        )
        client_call = AnthropicToolUseBlock(
            id="toolu_search",
            name="search",
            input={"q": "llipta"},
            caller={
                "type": "code_execution_20260120",
                "tool_id": "srvtoolu_code",
            },
            type="tool_use",
        )
        container = Container(
            id="container_123",
            expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        )
        provider = _build_provider(
            [
                _build_response(
                    [code_execution, client_call],
                    stop_reason="tool_use",
                    container=container,
                ),
                _build_response([AnthropicTextBlock(type="text", text="done")]),
            ]
        )
        initial = Message(role="user", content=[TextBlock(text="research")])
        turn = _complete(provider, messages=[initial])
        assistant = Message(
            role="assistant",
            content=turn.replay_content,
            provider_state=turn.provider_state,
        )
        tool_result = Message(
            role="user",
            content=[
                ToolResultBlock(
                    tool_use_id="toolu_search",
                    content={"results": []},
                )
            ],
        )

        # Act
        _complete(provider, messages=[initial, assistant, tool_result])

        # Assert: the next request resumes the exact pending execution rather
        # than asking Anthropic to start a new container.
        followup = provider._client.messages.calls[1]
        self.assertEqual(followup["container"], "container_123")
        replayed_call = followup["messages"][1]["content"][1]
        self.assertEqual(
            replayed_call["caller"],
            {
                "type": "code_execution_20260120",
                "tool_id": "srvtoolu_code",
            },
        )

    def test_pending_programmatic_calls_without_container_fail_before_the_api(self):
        # Arrange: the latest assistant turn carries a tool call issued by
        # server-side code execution, but nothing in the history recorded a
        # container id -- a conversation persisted before container state was
        # captured, or one whose state was compacted away. Anthropic rejects
        # that request unconditionally, so the provider must not spend the
        # call to hear it.
        provider = _build_provider(
            [_build_response([AnthropicTextBlock(type="text", text="unreached")])]
        )
        messages = [
            Message(role="user", content=[TextBlock(text="research")]),
            Message(
                role="assistant",
                content=[
                    ToolUseBlock(
                        id="toolu_search",
                        name="search",
                        input={"q": "llipta"},
                        data={
                            "type": "tool_use",
                            "id": "toolu_search",
                            "name": "search",
                            "input": {"q": "llipta"},
                            "caller": {
                                "type": "code_execution_20260120",
                                "tool_id": "srvtoolu_code",
                            },
                        },
                    )
                ],
                # No provider_state: the container id was never recorded.
            ),
            Message(
                role="user",
                content=[
                    ToolResultBlock(tool_use_id="toolu_search", content={"results": []})
                ],
            ),
        ]

        # Act / Assert: rejected client-side, naming the unresumable state.
        with self.assertRaisesMessage(ProviderError, "no container id"):
            _complete(provider, messages=messages)
        self.assertEqual(provider._client.messages.calls, [])

    def test_open_code_execution_span_without_container_fails_before_the_api(self):
        # Arrange: the observed production shape -- a turn whose code
        # execution span never resolved and whose client tool calls carry no
        # ``caller`` metadata, from a response that disclosed no container.
        # The API demands the container to resume that code; without an id
        # there is nothing valid to send.
        provider = _build_provider(
            [_build_response([AnthropicTextBlock(type="text", text="unreached")])]
        )
        messages = [
            Message(role="user", content=[TextBlock(text="research")]),
            Message(
                role="assistant",
                content=[
                    ServerToolBlock(
                        data={
                            "type": "server_tool_use",
                            "id": "srvtoolu_code",
                            "name": "code_execution",
                            "input": {"code": "await search(...)"},
                        }
                    ),
                    ToolUseBlock(
                        id="toolu_search", name="search", input={"q": "llipta"}
                    ),
                ],
                # No provider_state: the response never disclosed a container.
            ),
            Message(
                role="user",
                content=[
                    ToolResultBlock(tool_use_id="toolu_search", content={"results": []})
                ],
            ),
        ]

        # Act / Assert
        with self.assertRaisesMessage(ProviderError, "no container id"):
            _complete(provider, messages=messages)
        self.assertEqual(provider._client.messages.calls, [])

    def test_response_without_required_container_is_retried_before_recording(self):
        # Arrange: Platform occasionally leaves dynamic-filtering code open but
        # omits the container required to replay it. The second response is a
        # clean rerun of the identical request.
        unresolved = ServerToolUseBlock(
            id="srvtoolu_code",
            name="code_execution",
            input={"code": "await web_search(...)"},
            type="server_tool_use",
        )
        provider = _build_provider(
            [
                _build_response([unresolved], stop_reason="pause_turn"),
                _build_response([AnthropicTextBlock(type="text", text="recovered")]),
            ]
        )

        # Act
        turn = _complete(provider)

        # Assert: the poisoned response never leaves the adapter; the retry's
        # answer does, with spend from both requests accounted for.
        self.assertEqual(turn.text, "recovered")
        self.assertEqual(len(provider._client.messages.calls), 2)
        self.assertEqual(turn.usage.input_tokens, 20)
        self.assertEqual(turn.usage.output_tokens, 6)

    def test_missing_container_retry_resets_discarded_stream_output(self):
        # Arrange
        unresolved = ServerToolUseBlock(
            id="srvtoolu_code",
            name="code_execution",
            input={"code": "await web_search(...)"},
            type="server_tool_use",
        )
        responses = [
            (
                _build_response([unresolved], stop_reason="pause_turn"),
                [
                    SimpleNamespace(
                        type="content_block_delta",
                        index=0,
                        delta=SimpleNamespace(type="text_delta", text="discarded"),
                    )
                ],
            ),
            (
                _build_response([AnthropicTextBlock(type="text", text="accepted")]),
                [
                    SimpleNamespace(
                        type="content_block_delta",
                        index=0,
                        delta=SimpleNamespace(type="text_delta", text="accepted"),
                    )
                ],
            ),
        ]

        class Messages:
            def stream(self, **_kwargs):
                response, events = responses.pop(0)
                return _FakeStream(response, events)

        provider = ClaudePlatformProvider(
            client=SimpleNamespace(messages=Messages()), model_id="claude-opus-5"
        )
        observed = []

        # Act
        provider.complete_with_events(
            system_prompt="sys",
            messages=[Message(role="user", content=[TextBlock(text="hi")])],
            rendered_tools=[],
            max_tokens=100,
            temperature=0.0,
            on_event=observed.append,
        )

        # Assert
        self.assertEqual(
            observed,
            [
                TextStreamDelta(block_index=0, text="discarded"),
                StreamReset(),
                TextStreamDelta(block_index=0, text="accepted"),
            ],
        )

    def test_repeated_missing_container_fails_without_returning_poisoned_turn(self):
        # Arrange
        unresolved = ServerToolUseBlock(
            id="srvtoolu_code",
            name="code_execution",
            input={"code": "await web_search(...)"},
            type="server_tool_use",
        )
        provider = _build_provider(
            [
                _build_response([unresolved], stop_reason="pause_turn"),
                _build_response([unresolved], stop_reason="pause_turn"),
            ]
        )

        # Act / Assert: the provider fails before returning an AssistantTurn,
        # so the agent recorder cannot append either unreplayable response.
        with self.assertRaisesMessage(ProviderError, "unreplayable response"):
            _complete(provider)
        self.assertEqual(len(provider._client.messages.calls), 2)

    def test_cancellation_probe_stops_missing_container_retry(self):
        # Arrange
        unresolved = ServerToolUseBlock(
            id="srvtoolu_code",
            name="code_execution",
            input={"code": "await web_search(...)"},
            type="server_tool_use",
        )
        provider = _build_provider(
            [
                _build_response([unresolved], stop_reason="pause_turn"),
                _build_response([AnthropicTextBlock(type="text", text="unreached")]),
            ]
        )

        def cancelled():
            raise InterruptedError("agent execution is no longer running")

        # Act / Assert: cancellation lands after the first response but before
        # the provider can issue its hidden second request.
        with self.assertRaises(InterruptedError):
            _complete(provider, before_retry=cancelled)
        self.assertEqual(len(provider._client.messages.calls), 1)

    def test_open_web_search_span_needs_no_container(self):
        # Arrange: a paused plain web search is resumable without any
        # container -- only open *code execution* gates on one.
        provider = _build_provider(
            [_build_response([AnthropicTextBlock(type="text", text="resumed")])]
        )
        messages = [
            Message(role="user", content=[TextBlock(text="research")]),
            Message(
                role="assistant",
                content=[
                    ServerToolBlock(
                        data={
                            "type": "server_tool_use",
                            "id": "srvtoolu_search",
                            "name": "web_search",
                            "input": {"query": "llipta"},
                        }
                    ),
                ],
            ),
        ]

        # Act
        turn = _complete(provider, messages=messages)

        # Assert
        self.assertEqual(turn.text, "resumed")
        self.assertNotIn("container", provider._client.messages.calls[0])

    def test_ordinary_requests_need_no_container(self):
        # Arrange: no programmatic tool calls anywhere -- the common case must
        # not be gated on container state.
        provider = _build_provider(
            [_build_response([AnthropicTextBlock(type="text", text="hello")])]
        )

        # Act
        turn = _complete(provider)

        # Assert
        self.assertEqual(turn.text, "hello")
        self.assertNotIn("container", provider._client.messages.calls[0])

    def test_code_execution_container_survives_multihop_tool_calls(self):
        # Arrange: the first programmatic call establishes a container. The
        # next response pauses for another call without repeating the already
        # active container, matching a multi-hop code-execution run.
        container = Container(
            id="container_123",
            expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        )
        first_call = AnthropicToolUseBlock(
            id="toolu_search_1",
            name="search",
            input={"q": "llipta"},
            caller={
                "type": "code_execution_20260120",
                "tool_id": "srvtoolu_code",
            },
            type="tool_use",
        )
        second_call = AnthropicToolUseBlock(
            id="toolu_search_2",
            name="search",
            input={"q": "quarry"},
            caller={
                "type": "code_execution_20260120",
                "tool_id": "srvtoolu_code",
            },
            type="tool_use",
        )
        provider = _build_provider(
            [
                _build_response(
                    [first_call],
                    stop_reason="tool_use",
                    container=container,
                ),
                _build_response([second_call], stop_reason="tool_use"),
                _build_response([AnthropicTextBlock(type="text", text="done")]),
            ]
        )
        initial = Message(role="user", content=[TextBlock(text="research")])
        first_turn = _complete(provider, messages=[initial])
        first_assistant = Message(
            role="assistant",
            content=first_turn.replay_content,
            provider_state=first_turn.provider_state,
        )
        first_result = Message(
            role="user",
            content=[
                ToolResultBlock(
                    tool_use_id="toolu_search_1",
                    content={"results": []},
                )
            ],
        )
        first_history = [initial, first_assistant, first_result]
        second_turn = _complete(provider, messages=first_history)
        second_assistant = Message(
            role="assistant",
            content=second_turn.replay_content,
            provider_state=second_turn.provider_state,
        )
        second_result = Message(
            role="user",
            content=[
                ToolResultBlock(
                    tool_use_id="toolu_search_2",
                    content={"results": []},
                )
            ],
        )

        # Act
        _complete(
            provider,
            messages=[*first_history, second_assistant, second_result],
        )

        # Assert: omission on the intermediate response does not clear the
        # active container required by the second programmatic tool result.
        self.assertEqual(
            provider._client.messages.calls[1]["container"], "container_123"
        )
        self.assertEqual(
            provider._client.messages.calls[2]["container"], "container_123"
        )

    def test_code_execution_container_survives_an_ordinary_tool_turn(self):
        # Arrange: with web-search dynamic filtering the API runs code execution
        # inside the turn, so the model mixes ordinary tool calls with ones its
        # filtering code issues. Here the container is established on a turn
        # whose own client call is ordinary, and the *next* turn pauses on a
        # code-generated call without repeating the container.
        container = Container(
            id="container_123",
            expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        )
        ordinary_call = AnthropicToolUseBlock(
            id="toolu_search",
            name="search",
            input={"q": "llipta"},
            type="tool_use",
        )
        programmatic_call = AnthropicToolUseBlock(
            id="toolu_verify",
            name="verify",
            input={"doi": "10.1/x"},
            caller={
                "type": "code_execution_20260120",
                "tool_id": "srvtoolu_code",
            },
            type="tool_use",
        )
        provider = _build_provider(
            [
                _build_response(
                    [*_build_server_search_blocks(), ordinary_call],
                    stop_reason="tool_use",
                    container=container,
                ),
                _build_response([programmatic_call], stop_reason="tool_use"),
                _build_response([AnthropicTextBlock(type="text", text="done")]),
            ]
        )
        initial = Message(role="user", content=[TextBlock(text="research")])
        search_turn = _complete(provider, messages=[initial])
        history = [
            initial,
            Message(
                role="assistant",
                content=search_turn.replay_content,
                provider_state=search_turn.provider_state,
            ),
            Message(
                role="user",
                content=[
                    ToolResultBlock(tool_use_id="toolu_search", content={"results": []})
                ],
            ),
        ]
        verify_turn = _complete(provider, messages=history)

        # Act
        _complete(
            provider,
            messages=[
                *history,
                Message(
                    role="assistant",
                    content=verify_turn.replay_content,
                    provider_state=verify_turn.provider_state,
                ),
                Message(
                    role="user",
                    content=[
                        ToolResultBlock(
                            tool_use_id="toolu_verify", content={"results": []}
                        )
                    ],
                ),
            ],
        )

        # Assert: the ordinary call does not retire the container, so the
        # code-generated call's result carries the id Anthropic requires. Without
        # it the API rejects the turn: "container_id is required when there are
        # pending tool uses generated by code execution with tools".
        self.assertEqual(
            provider._client.messages.calls[2]["container"], "container_123"
        )

    def test_container_outlives_its_recorded_expiry_on_a_paused_turn(self):
        # Arrange: a ``pause_turn`` continuation -- the loop resubmits the paused
        # assistant turn with no user turn after it, so this request carries no
        # client tool calls of any kind, and the only expiry Anthropic ever sent
        # for the container has passed. ``expires_at`` is a short rolling value
        # that does not report the real limit: the container lives 30 days from
        # creation and idling only checkpoints it, so a passed timestamp says
        # nothing about whether the id still works.
        provider = _build_provider(
            [_build_response([AnthropicTextBlock(type="text", text="answer")])]
        )
        history = [
            Message(role="user", content=[TextBlock(text="research")]),
            Message(
                role="assistant",
                content=[
                    ServerToolBlock(data=block.model_dump(mode="json"))
                    for block in _build_server_search_blocks()
                ],
                provider_state={
                    "anthropic": {
                        "container": {
                            "id": "container_old",
                            "expires_at": "2020-01-01T00:00:00Z",
                        }
                    }
                },
            ),
        ]

        # Act
        _complete(provider, messages=history)

        # Assert: neither a stale timestamp nor the absence of code-generated
        # calls retires the container. Guessing it dead drops an id the API may
        # still require, while a reclaimed id costs at most the same failed turn.
        self.assertEqual(
            provider._client.messages.calls[0]["container"], "container_old"
        )

    def test_cited_text_replays_with_encrypted_metadata(self):
        # Arrange: a server search can produce cited text and a client tool call
        # in the same assistant turn. The follow-up must replay every citation
        # field, including its encrypted index.
        cited_text = AnthropicTextBlock(
            type="text",
            text="The result supports the claim.",
            citations=[
                {
                    "type": "web_search_result_location",
                    "cited_text": "supporting passage",
                    "encrypted_index": "enc-index",
                    "title": "Source",
                    "url": "https://example.org/source",
                }
            ],
        )
        response = _build_response(
            [
                *_build_server_search_blocks(),
                cited_text,
                AnthropicToolUseBlock(
                    type="tool_use",
                    id="t1",
                    name="submit_proposal",
                    input={"sections": {}},
                ),
            ],
            stop_reason="tool_use",
        )
        provider = _build_provider([response], web_search=True)
        turn = _complete(provider)

        # Act
        rendered = provider._render_messages(
            [Message(role="assistant", content=turn.replay_content)]
        )

        # Assert
        replayed_text = rendered[0]["content"][-2]
        self.assertEqual(
            replayed_text,
            cited_text.model_dump(mode="json", exclude_none=True),
        )
        self.assertEqual(
            replayed_text["citations"][0]["encrypted_index"],
            "enc-index",
        )

    def test_unknown_content_block_is_preserved_for_forward_compatibility(self):
        # Arrange: stand in for a complete block returned by a newer API/SDK.
        payload = {
            "type": "something_new",
            "encrypted_state": "opaque",
        }
        response = SimpleNamespace(
            content=[payload],
            stop_reason="end_turn",
            usage=Usage(input_tokens=10, output_tokens=3),
        )
        provider = _build_provider([response])

        # Act
        with self.assertLogs(
            "research_ai.services.agent.providers.claude_platform",
            level="WARNING",
        ) as logs:
            turn = _complete(provider)
        rendered = provider._render_messages(
            [Message(role="assistant", content=turn.replay_content)]
        )

        # Assert: the run survives and the provider gets back exactly what it
        # returned, while operators can see that the adapter needs updating.
        self.assertEqual(rendered[0]["content"], [payload])
        self.assertIn("something_new", "\n".join(logs.output))

    def test_unknown_content_block_without_payload_fails_safely(self):
        # Arrange: a type name alone cannot be replayed without data loss.
        response = SimpleNamespace(
            content=[SimpleNamespace(type="something_new")],
            stop_reason="end_turn",
            usage=Usage(input_tokens=10, output_tokens=3),
        )
        provider = _build_provider([response])

        # Act / Assert
        with self.assertRaisesRegex(
            ProviderError,
            "content block cannot be replayed safely: 'something_new'",
        ):
            _complete(provider)

    def test_pause_turn_is_a_resumable_stop_not_an_unknown_one(self):
        # Arrange: the API spent its per-turn budget of server-side calls.
        provider = _build_provider(
            [_build_response(_build_server_search_blocks(), stop_reason="pause_turn")]
        )

        # Act
        turn = _complete(provider)

        # Assert: distinct from OTHER, which the loop treats as a dead turn.
        self.assertEqual(turn.stop_reason, StopReason.PAUSE_TURN)

    def test_cache_breakpoint_skips_a_block_that_must_not_be_edited(self):
        # Arrange: a paused turn is resumed with the assistant turn last, so the
        # trailing block is one the provider validates exactly as it sent it.
        provider = _build_provider()
        messages = [
            Message(role="user", content=[TextBlock(text="hi")]),
            Message(
                role="assistant",
                content=[
                    ServerToolBlock(
                        data={
                            "type": "web_search_tool_result",
                            "tool_use_id": "s1",
                            "content": [],
                        }
                    )
                ],
            ),
        ]

        # Act
        rendered = provider._render_messages(messages, cache_last=True)

        # Assert: left unmarked (the tools+system breakpoint still stands).
        self.assertNotIn("cache_control", rendered[-1]["content"][-1])

    def test_cache_breakpoint_still_lands_on_an_ordinary_turn(self):
        # Arrange: the usual case -- the loop completes from a user turn.
        provider = _build_provider()
        messages = [
            Message(
                role="user",
                content=[ToolResultBlock(tool_use_id="t1", content={"ok": True})],
            )
        ]

        # Act
        rendered = provider._render_messages(messages, cache_last=True)

        # Assert
        self.assertEqual(
            rendered[-1]["content"][-1]["cache_control"], {"type": "ephemeral"}
        )
