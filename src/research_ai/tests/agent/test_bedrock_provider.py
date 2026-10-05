"""Unit tests for the Bedrock Converse provider adapter (no network)."""

from copy import deepcopy

from django.test import SimpleTestCase

from research_ai.services.agent.errors import ProviderError
from research_ai.services.agent.images import MANY_IMAGES, ImageUnavailableError
from research_ai.services.agent.providers import bedrock
from research_ai.services.agent.providers.bedrock import BedrockProvider
from research_ai.services.agent.tools import Tool
from research_ai.services.agent.types import (
    ImageBlock,
    Message,
    StopReason,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    TurnUsage,
)
from research_ai.tests.agent.image_test_helpers import JPEG, PNG, WIDE_PNG


class FakeConverseClient:
    """Returns queued Converse responses; records the kwargs it was sent."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        return self._responses.pop(0)


def _build_provider(responses=None, model_id="test-model", **kwargs):
    """Build a BedrockProvider with a fake client so no AWS client is constructed."""
    return BedrockProvider(
        client=FakeConverseClient(responses or []), model_id=model_id, **kwargs
    )


class RenderToolsTests(SimpleTestCase):
    def test_render_tools_produces_tool_spec_shape(self):
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
            {
                "tools": [
                    {
                        "toolSpec": {
                            "name": "search",
                            "description": "search things",
                            "inputSchema": {
                                "json": {"type": "object", "properties": {}}
                            },
                        }
                    }
                ]
            },
        )


class RenderMessagesTests(SimpleTestCase):
    def test_blocks_render_to_converse_wire_shapes(self):
        # Arrange
        provider = _build_provider()
        messages = [
            Message(role="user", content=[TextBlock(text="hi")]),
            Message(
                role="assistant",
                content=[ToolUseBlock(id="t1", name="search", input={"q": 1})],
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

        # Assert: text, toolUse, and toolResult shapes (with error status).
        self.assertEqual(rendered[0]["content"][0], {"text": "hi"})
        self.assertEqual(
            rendered[1]["content"][0],
            {"toolUse": {"toolUseId": "t1", "name": "search", "input": {"q": 1}}},
        )
        self.assertEqual(
            rendered[2]["content"][0],
            {"toolResult": {"toolUseId": "t1", "content": [{"json": {"ok": True}}]}},
        )
        self.assertEqual(rendered[2]["content"][1]["toolResult"]["status"], "error")

    def test_reasoning_blocks_render_back_verbatim(self):
        # Arrange: signed reasoning must replay unedited on the next turn.
        provider = _build_provider()
        payload = {"reasoningText": {"text": "step one", "signature": "sig"}}
        messages = [
            Message(role="assistant", content=[ThinkingBlock(data=payload)]),
        ]

        # Act
        rendered = provider._render_messages(messages)

        # Assert
        self.assertEqual(rendered[0]["content"][0], {"reasoningContent": payload})


class RenderImageTests(SimpleTestCase):
    PAGE = ImageBlock(ref="files/1/p1.jpg", media_type="image/jpeg", label="Page 1")
    CHART = ImageBlock(ref="files/1/chart.png", media_type="image/png")
    WIDE = ImageBlock(ref="files/1/wide.png", media_type="image/png", label="wide")
    IMAGES = {
        "files/1/p1.jpg": JPEG,
        "files/1/chart.png": PNG,
        "files/1/wide.png": WIDE_PNG,
    }

    def _provider(self, model_id="us.anthropic.claude-opus-5"):
        return _build_provider(model_id=model_id, image_loader=self.IMAGES.__getitem__)

    def test_user_images_render_as_raw_bytes_after_their_label(self):
        # Arrange
        messages = [
            Message(role="user", content=[self.PAGE, TextBlock(text="what is this?")])
        ]

        # Act
        rendered = self._provider()._render_messages(messages)

        # Assert
        self.assertEqual(
            rendered[0]["content"],
            [
                {"text": "Page 1"},
                {"image": {"format": "jpeg", "source": {"bytes": JPEG}}},
                {"text": "what is this?"},
            ],
        )

    def test_tool_result_images_render_inside_the_result(self):
        # Arrange
        messages = [
            Message(
                role="user",
                content=[
                    ToolResultBlock(
                        tool_use_id="t1", content={"page": 1}, images=(self.CHART,)
                    )
                ],
            )
        ]

        # Act
        rendered = self._provider()._render_messages(messages)

        # Assert
        self.assertEqual(
            rendered[0]["content"],
            [
                {
                    "toolResult": {
                        "toolUseId": "t1",
                        "content": [
                            {"json": {"page": 1}},
                            {
                                "image": {
                                    "format": "png",
                                    "source": {"bytes": PNG},
                                }
                            },
                        ],
                    }
                }
            ],
        )

    def test_a_model_not_known_to_take_images_gets_placeholders(self):
        # Arrange
        messages = [
            Message(role="user", content=[self.PAGE, TextBlock(text="what is this?")])
        ]

        # Act
        rendered = self._provider(model_id="us.meta.llama4")._render_messages(messages)

        # Assert
        self.assertEqual(
            rendered[0]["content"],
            [{"text": "[Image not shown: Page 1]"}, {"text": "what is this?"}],
        )

    def test_an_image_over_the_bedrock_limit_is_not_sent(self):
        # Arrange
        provider = _build_provider(
            model_id="us.anthropic.claude-opus-5",
            image_loader=lambda ref: PNG + b"x" * bedrock.MAX_IMAGE_BYTES,
        )
        messages = [Message(role="user", content=[self.CHART])]

        # Act
        with self.assertLogs("research_ai.services.agent.images", "WARNING"):
            rendered = provider._render_messages(messages)

        # Assert
        self.assertEqual(rendered[0]["content"], [{"text": "[Image not shown]"}])

    def test_a_message_sends_no_more_images_than_bedrock_allows(self):
        # Arrange
        pages = [self.CHART] * (bedrock.MAX_MESSAGE_IMAGES + 1)
        messages = [Message(role="user", content=[*pages, TextBlock(text="compare")])]

        # Act
        with self.assertLogs("research_ai.services.agent.providers.bedrock", "WARNING"):
            rendered = self._provider()._render_messages(messages)

        # Assert
        content = rendered[0]["content"]
        self.assertEqual(
            sum("image" in part for part in content), bedrock.MAX_MESSAGE_IMAGES
        )
        self.assertEqual(
            content[-2:], [{"text": "[Image not shown]"}, {"text": "compare"}]
        )

    def test_tool_results_in_one_message_share_its_image_limit(self):
        # Arrange
        per_result = bedrock.MAX_MESSAGE_IMAGES - 1
        messages = [
            Message(
                role="user",
                content=[
                    ToolResultBlock(
                        tool_use_id=tool_use_id,
                        content={},
                        images=(self.CHART,) * per_result,
                    )
                    for tool_use_id in ("t1", "t2")
                ],
            )
        ]

        # Act
        with self.assertLogs("research_ai.services.agent.providers.bedrock", "WARNING"):
            rendered = self._provider()._render_messages(messages)

        # Assert
        first, second = (
            part["toolResult"]["content"] for part in rendered[0]["content"]
        )
        self.assertEqual(sum("image" in part for part in first), per_result)
        self.assertEqual(sum("image" in part for part in second), 1)
        self.assertEqual(second[2:], [{"text": "[Image not shown]"}] * (per_result - 1))

    def test_the_image_limit_applies_to_each_message_separately(self):
        # Arrange
        full = Message(role="user", content=[self.CHART] * bedrock.MAX_MESSAGE_IMAGES)
        reply = Message(role="assistant", content=[TextBlock(text="ok")])

        # Act
        rendered = self._provider()._render_messages([full, reply, full])

        # Assert
        for message in (rendered[0], rendered[2]):
            self.assertEqual(
                sum("image" in part for part in message["content"]),
                bedrock.MAX_MESSAGE_IMAGES,
            )

    def test_an_image_that_is_not_sent_leaves_its_place_to_the_next(self):
        # Arrange
        gone = ImageBlock(ref="files/9/gone.png", media_type="image/png")
        images = dict(self.IMAGES)

        def loader(ref):
            if ref not in images:
                raise ImageUnavailableError(ref)
            return images[ref]

        provider = _build_provider(
            model_id="us.anthropic.claude-opus-5", image_loader=loader
        )
        pages = [gone, *[self.CHART] * bedrock.MAX_MESSAGE_IMAGES]

        # Act
        with self.assertLogs("research_ai.services.agent.images", "WARNING"):
            rendered = provider._render_messages([Message(role="user", content=pages)])

        # Assert
        content = rendered[0]["content"]
        self.assertEqual(content[0], {"text": "[Image not shown]"})
        self.assertEqual(
            sum("image" in part for part in content), bedrock.MAX_MESSAGE_IMAGES
        )

    def test_a_large_image_is_not_sent_once_the_request_has_many_images(self):
        # Arrange
        others = [
            Message(role="user", content=[self.CHART] * MANY_IMAGES),
            Message(role="assistant", content=[TextBlock(text="ok")]),
        ]
        wide = Message(role="user", content=[self.WIDE])

        # Act
        alone = self._provider()._render_messages([wide])
        with self.assertLogs("research_ai.services.agent.images", "WARNING"):
            among_many = self._provider()._render_messages([*others, wide])

        # Assert
        self.assertEqual(
            alone[0]["content"],
            [
                {"text": "wide"},
                {"image": {"format": "png", "source": {"bytes": WIDE_PNG}}},
            ],
        )
        self.assertEqual(
            among_many[2]["content"], [{"text": "[Image not shown: wide]"}]
        )


class CompleteAndParseTests(SimpleTestCase):
    def test_parses_reasoning_content_into_thinking_blocks(self):
        # Arrange: Opus 5 thinks by default, so a turn can carry reasoning.
        reasoning = {"reasoningText": {"text": "step one", "signature": "sig"}}
        response = {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {"reasoningContent": reasoning},
                        {"text": "done"},
                    ],
                }
            },
            "stopReason": "end_turn",
        }
        provider = _build_provider([response])

        # Act
        turn = provider.complete(
            system_prompt="sys",
            messages=[Message(role="user", content=[TextBlock(text="hi")])],
            rendered_tools={"tools": []},
            max_tokens=100,
            temperature=0.0,
        )

        # Assert: captured whole, alongside the visible text.
        self.assertEqual([b.data for b in turn.thinking_blocks], [reasoning])
        self.assertEqual(turn.text, "done")

    def test_none_max_tokens_resolves_to_the_adapter_output_ceiling(self):
        # Arrange
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}},
            "stopReason": "end_turn",
        }
        provider = _build_provider([response])

        # Act
        provider.complete(
            system_prompt="sys",
            messages=[Message(role="user", content=[TextBlock(text="hi")])],
            rendered_tools={"tools": []},
            max_tokens=None,
            temperature=0.0,
        )

        # Assert
        self.assertEqual(
            provider._client.calls[0]["inferenceConfig"]["maxTokens"],
            bedrock.MAX_OUTPUT_TOKENS,
        )

    def test_omits_temperature_for_opus_5(self):
        # Arrange: the new default model rejects sampling params with a 400.
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}},
            "stopReason": "end_turn",
        }
        provider = BedrockProvider(client=FakeConverseClient([response]))

        # Act
        provider.complete(
            system_prompt="sys",
            messages=[Message(role="user", content=[TextBlock(text="hi")])],
            rendered_tools={"tools": []},
            max_tokens=100,
            temperature=0.0,
        )

        # Assert
        self.assertNotIn("temperature", provider._client.calls[0]["inferenceConfig"])

    def test_complete_parses_text_and_tool_use_and_stop_reason(self):
        # Arrange
        response = {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {"text": "let me search"},
                        {
                            "toolUse": {
                                "toolUseId": "t1",
                                "name": "search",
                                "input": {"q": "jane"},
                            }
                        },
                    ],
                }
            },
            "stopReason": "tool_use",
        }
        provider = _build_provider([response])

        # Act
        turn = provider.complete(
            system_prompt="sys",
            messages=[Message(role="user", content=[TextBlock(text="hi")])],
            rendered_tools={"tools": [{"toolSpec": {"name": "search"}}]},
            max_tokens=100,
            temperature=0.0,
        )

        # Assert
        self.assertEqual(turn.text, "let me search")
        self.assertEqual(len(turn.tool_calls), 1)
        self.assertEqual(turn.tool_calls[0].id, "t1")
        self.assertEqual(turn.tool_calls[0].input, {"q": "jane"})
        self.assertEqual(turn.stop_reason, StopReason.TOOL_USE)
        # toolConfig was forwarded because tools were present.
        self.assertIn("toolConfig", provider._client.calls[0])

    def test_omits_temperature_for_models_that_reject_sampling_params(self):
        # Arrange: Opus 4.8 rejects `temperature` with a 400.
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}},
            "stopReason": "end_turn",
        }
        provider = BedrockProvider(
            client=FakeConverseClient([response]),
            model_id="us.anthropic.claude-opus-4-8",
        )

        # Act
        provider.complete(
            system_prompt="sys",
            messages=[Message(role="user", content=[TextBlock(text="hi")])],
            rendered_tools={"tools": []},
            max_tokens=100,
            temperature=0.0,
        )

        # Assert: temperature is not forwarded; maxTokens still is.
        inference_config = provider._client.calls[0]["inferenceConfig"]
        self.assertNotIn("temperature", inference_config)
        self.assertEqual(inference_config["maxTokens"], 100)

    def test_includes_temperature_for_models_that_accept_it(self):
        # Arrange: a sampling-friendly model (e.g. Sonnet/Haiku) keeps temperature.
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}},
            "stopReason": "end_turn",
        }
        provider = BedrockProvider(
            client=FakeConverseClient([response]),
            model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        )

        # Act
        provider.complete(
            system_prompt="sys",
            messages=[Message(role="user", content=[TextBlock(text="hi")])],
            rendered_tools={"tools": []},
            max_tokens=100,
            temperature=0.0,
        )

        # Assert
        self.assertEqual(
            provider._client.calls[0]["inferenceConfig"]["temperature"], 0.0
        )

    def test_prompt_caching_adds_cache_points_to_system_and_last_message(self):
        # Arrange
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 10, "cacheReadInputTokens": 5, "outputTokens": 2},
        }
        provider = _build_provider([response])
        provider.prompt_caching = True

        # Act
        provider.complete(
            system_prompt="sys",
            messages=[Message(role="user", content=[TextBlock(text="hi")])],
            rendered_tools={"tools": []},
            max_tokens=100,
            temperature=0.0,
        )

        # Assert: cache point trails both the system prompt and the last message.
        call = provider._client.calls[0]
        self.assertEqual(call["system"][-1], {"cachePoint": {"type": "default"}})
        self.assertEqual(
            call["messages"][-1]["content"][-1], {"cachePoint": {"type": "default"}}
        )

    def test_prompt_caching_disabled_emits_no_cache_points(self):
        # Arrange
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}},
            "stopReason": "end_turn",
        }
        provider = _build_provider([response])
        provider.prompt_caching = False

        # Act
        provider.complete(
            system_prompt="sys",
            messages=[Message(role="user", content=[TextBlock(text="hi")])],
            rendered_tools={"tools": []},
            max_tokens=100,
            temperature=0.0,
        )

        # Assert: no cache points anywhere.
        call = provider._client.calls[0]
        self.assertEqual(call["system"], [{"text": "sys"}])
        self.assertNotIn(
            {"cachePoint": {"type": "default"}}, call["messages"][-1]["content"]
        )

    def test_complete_fills_usage_and_latency_from_response(self):
        # Arrange: Converse reports usage and latency alongside the message.
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}},
            "stopReason": "end_turn",
            "usage": {
                "inputTokens": 10,
                "outputTokens": 3,
                "cacheReadInputTokens": 5,
                "cacheWriteInputTokens": 2,
            },
            "metrics": {"latencyMs": 1234},
        }
        provider = _build_provider([response])

        # Act
        turn = provider.complete(
            system_prompt="sys",
            messages=[Message(role="user", content=[TextBlock(text="hi")])],
            rendered_tools={"tools": []},
            max_tokens=100,
            temperature=0.0,
        )

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
        self.assertEqual(turn.latency_ms, 1234)

    def test_missing_usage_and_metrics_leave_turn_metadata_none(self):
        # Arrange: a response without usage/metrics (as fakes and older shapes omit).
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}},
            "stopReason": "end_turn",
        }
        provider = _build_provider([response])

        # Act
        turn = provider.complete(
            system_prompt="sys",
            messages=[Message(role="user", content=[TextBlock(text="hi")])],
            rendered_tools={"tools": []},
            max_tokens=100,
            temperature=0.0,
        )

        # Assert: absent metadata is None, not zeroed.
        self.assertIsNone(turn.usage)
        self.assertIsNone(turn.latency_ms)

    def test_parse_turn_maps_unknown_stop_reason_to_other(self):
        # Arrange
        provider = _build_provider()
        response = {
            "output": {"message": {"role": "assistant", "content": []}},
            "stopReason": "something_new",
        }

        # Act
        turn = provider._parse_turn(response)

        # Assert
        self.assertEqual(turn.stop_reason, StopReason.OTHER)

    def test_missing_output_message_raises(self):
        # Arrange
        provider = _build_provider([{"stopReason": "end_turn"}])

        # Act / Assert
        with self.assertRaises(ProviderError):
            provider.complete(
                system_prompt="sys",
                messages=[Message(role="user", content=[TextBlock(text="hi")])],
                rendered_tools={"tools": []},
                max_tokens=100,
                temperature=0.0,
            )

    def test_converse_exception_raises_provider_error(self):
        # Arrange: the boto3 client dies (throttling, network, etc.).
        class ExplodingClient:
            def converse(self, **kwargs):
                raise ValueError("ThrottlingException")

        provider = BedrockProvider(client=ExplodingClient(), model_id="test-model")

        # Act / Assert: typed, chained to the original client error.
        with self.assertRaisesRegex(ProviderError, "ThrottlingException") as ctx:
            provider.complete(
                system_prompt="sys",
                messages=[Message(role="user", content=[TextBlock(text="hi")])],
                rendered_tools={"tools": []},
                max_tokens=100,
                temperature=0.0,
            )
        self.assertIsInstance(ctx.exception.__cause__, ValueError)
