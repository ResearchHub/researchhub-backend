"""Unit tests for the provider registry (no network calls)."""

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from research_ai.services.agent.providers import registry
from research_ai.services.agent.providers.claude_platform import ClaudePlatformProvider
from research_ai.services.agent.providers.openrouter import OpenRouterProvider
from research_ai.services.agent.providers.registry import (
    generator_model_ref,
    resolve_provider,
    split_model_ref,
)


class GeneratorModelRefTests(SimpleTestCase):
    def test_default_ref_is_claude_platform(self):
        # Arrange / Act
        ref = generator_model_ref()

        # Assert
        self.assertEqual(ref, "claude_platform:claude-opus-5")

    @override_settings(RESEARCH_AI_GENERATOR_PROVIDER="bedrock")
    def test_bedrock_ref_carries_provider_prefix(self):
        # Arrange / Act
        ref = generator_model_ref()

        # Assert
        self.assertEqual(ref, "bedrock:us.anthropic.claude-opus-5")

    @override_settings(RESEARCH_AI_GENERATOR_PROVIDER="openrouter")
    def test_openrouter_ref_carries_provider_prefix(self):
        # Arrange / Act
        ref = generator_model_ref()

        # Assert
        self.assertEqual(ref, "openrouter:anthropic/claude-opus-5")

    @override_settings(RESEARCH_AI_GENERATOR_PROVIDER="acme")
    def test_unknown_provider_name_raises(self):
        # Arrange / Act / Assert
        with self.assertRaises(ValueError):
            generator_model_ref()


class SplitModelRefTests(SimpleTestCase):
    def test_prefixed_ref_splits_on_its_provider(self):
        # Act / Assert
        self.assertEqual(
            split_model_ref("openrouter:openai/gpt-5.6-sol"),
            ("openrouter", "openai/gpt-5.6-sol"),
        )

    def test_bare_ref_falls_back_to_the_generator_provider(self):
        # Act / Assert
        self.assertEqual(
            split_model_ref("claude-sonnet-5"), ("claude_platform", "claude-sonnet-5")
        )

    def test_prefix_alone_yields_no_model_id(self):
        # Act / Assert
        self.assertEqual(split_model_ref("bedrock:"), ("bedrock", None))


@patch.object(registry, "BedrockProvider")
class ResolveProviderTests(SimpleTestCase):
    def test_default_resolves_to_claude_platform(self, bedrock_cls):
        # Arrange / Act
        provider = resolve_provider()

        # Assert
        self.assertIsInstance(provider, ClaudePlatformProvider)
        self.assertEqual(provider.model_id, "claude-opus-5")
        self.assertEqual(provider.native_tool_names, frozenset())
        bedrock_cls.assert_not_called()

    def test_native_web_search_must_be_enabled_explicitly(self, bedrock_cls):
        # Arrange / Act
        provider = resolve_provider(native_tools=frozenset({"web_search"}))

        # Assert
        self.assertIsInstance(provider, ClaudePlatformProvider)
        self.assertEqual(provider.native_tool_names, frozenset({"web_search"}))
        bedrock_cls.assert_not_called()

    def test_bedrock_prefix_routes_to_bedrock(self, bedrock_cls):
        # Arrange / Act
        provider = resolve_provider("bedrock:us.meta.llama4")

        # Assert
        self.assertIs(provider, bedrock_cls.return_value)
        bedrock_cls.assert_called_once_with(model_id="us.meta.llama4")

    def test_claude_platform_prefix_is_stripped(self, bedrock_cls):
        # Arrange / Act
        provider = resolve_provider("claude_platform:claude-sonnet-5")

        # Assert
        self.assertIsInstance(provider, ClaudePlatformProvider)
        self.assertEqual(provider.model_id, "claude-sonnet-5")
        bedrock_cls.assert_not_called()

    def test_openrouter_prefix_routes_to_openrouter(self, bedrock_cls):
        # Arrange / Act
        provider = resolve_provider("openrouter:google/gemini-3-pro")

        # Assert
        self.assertIsInstance(provider, OpenRouterProvider)
        self.assertEqual(provider.model_id, "google/gemini-3-pro")
        self.assertEqual(provider.native_tool_names, frozenset())
        bedrock_cls.assert_not_called()

    def test_unprefixed_ref_uses_default_generator_provider(self, bedrock_cls):
        # Arrange / Act
        provider = resolve_provider("claude-haiku-4-5")

        # Assert
        self.assertIsInstance(provider, ClaudePlatformProvider)
        self.assertEqual(provider.model_id, "claude-haiku-4-5")
        bedrock_cls.assert_not_called()

    @override_settings(RESEARCH_AI_GENERATOR_PROVIDER="bedrock")
    def test_unprefixed_ref_follows_bedrock_generator(self, bedrock_cls):
        # Arrange / Act
        resolve_provider("us.anthropic.claude-opus-4-8")

        # Assert
        bedrock_cls.assert_called_once_with(model_id="us.anthropic.claude-opus-4-8")

    @override_settings(RESEARCH_AI_GENERATOR_PROVIDER="openrouter")
    def test_unprefixed_ref_follows_openrouter_generator(self, bedrock_cls):
        # Arrange / Act
        provider = resolve_provider("openai/gpt-5.4")

        # Assert
        self.assertIsInstance(provider, OpenRouterProvider)
        self.assertEqual(provider.model_id, "openai/gpt-5.4")
        bedrock_cls.assert_not_called()
