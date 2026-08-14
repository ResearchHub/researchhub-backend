"""Unit tests for the provider registry (no network calls)."""

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from research_ai.services.agent.providers import registry
from research_ai.services.agent.providers.claude_platform import ClaudePlatformProvider
from research_ai.services.agent.providers.openrouter import OpenRouterProvider
from research_ai.services.agent.providers.registry import (
    generator_model_ref,
    resolve_provider,
)


class GeneratorModelRefTests(SimpleTestCase):
    def test_default_ref_is_openrouter_kimi_k3(self):
        # Arrange / Act
        ref = generator_model_ref()

        # Assert
        self.assertEqual(ref, "openrouter:moonshotai/kimi-k3")

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
        self.assertEqual(ref, "openrouter:moonshotai/kimi-k3")

    @override_settings(RESEARCH_AI_GENERATOR_PROVIDER="acme")
    def test_unknown_provider_name_raises(self):
        # Arrange / Act / Assert
        with self.assertRaises(ValueError):
            generator_model_ref()


@patch.object(registry, "BedrockProvider")
class ResolveProviderTests(SimpleTestCase):
    def test_default_resolves_to_openrouter_kimi_k3(self, bedrock_cls):
        # Arrange / Act
        provider = resolve_provider()

        # Assert
        self.assertIsInstance(provider, OpenRouterProvider)
        self.assertEqual(provider.model_id, "moonshotai/kimi-k3")
        self.assertEqual(provider.native_tool_names, frozenset())
        bedrock_cls.assert_not_called()

    @override_settings(RESEARCH_AI_GENERATOR_PROVIDER="claude_platform")
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

    def test_unprefixed_ref_uses_default_openrouter_generator(self, bedrock_cls):
        # Arrange / Act
        provider = resolve_provider("moonshotai/kimi-k3")

        # Assert
        self.assertIsInstance(provider, OpenRouterProvider)
        self.assertEqual(provider.model_id, "moonshotai/kimi-k3")
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
