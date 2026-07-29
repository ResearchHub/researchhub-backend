"""Unit tests for the provider registry (no clients built)."""

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from research_ai.services.agent.providers import claude_platform, registry
from research_ai.services.agent.providers.claude_platform import ClaudePlatformProvider
from research_ai.services.agent.providers.registry import (
    generator_model_ref,
    resolve_provider,
)


class GeneratorModelRefTests(SimpleTestCase):
    def test_defaults_to_claude_platform_opus_5(self):
        # Arrange / Act
        ref = generator_model_ref()

        # Assert
        self.assertEqual(ref, "claude_platform:claude-opus-5")

    @patch.object(claude_platform, "MODEL_ID", "claude-sonnet-5")
    def test_claude_platform_ref_reads_its_module_default(self):
        # Arrange / Act
        ref = generator_model_ref()

        # Assert
        self.assertEqual(ref, "claude_platform:claude-sonnet-5")

    @override_settings(RESEARCH_AI_GENERATOR_PROVIDER="bedrock")
    def test_bedrock_ref_carries_the_provider_prefix(self):
        # Arrange / Act
        ref = generator_model_ref()

        # Assert
        self.assertEqual(ref, "bedrock:us.anthropic.claude-opus-5")

    @override_settings(RESEARCH_AI_GENERATOR_PROVIDER="acme")
    def test_unknown_provider_name_raises(self):
        # Arrange / Act / Assert
        with self.assertRaises(ValueError):
            generator_model_ref()


@patch.object(registry, "BedrockProvider")
class ResolveProviderTests(SimpleTestCase):
    def test_default_resolves_to_the_claude_platform_generator(self, bedrock_cls):
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

    def test_unprefixed_ref_stays_on_the_configured_generator(self, bedrock_cls):
        # Arrange / Act: the generator is Claude Platform by default.
        provider = resolve_provider("claude-haiku-4-5")

        # Assert
        self.assertIsInstance(provider, ClaudePlatformProvider)
        self.assertEqual(provider.model_id, "claude-haiku-4-5")
        bedrock_cls.assert_not_called()

    @override_settings(RESEARCH_AI_GENERATOR_PROVIDER="bedrock")
    def test_unprefixed_ref_follows_a_bedrock_generator(self, bedrock_cls):
        # Arrange / Act: an existing Bedrock roster keeps resolving to Bedrock.
        resolve_provider("us.anthropic.claude-opus-4-8")

        # Assert
        bedrock_cls.assert_called_once_with(model_id="us.anthropic.claude-opus-4-8")

    @override_settings(RESEARCH_AI_GENERATOR_PROVIDER="bedrock")
    def test_bedrock_generator_setting_resolves_bedrock(self, bedrock_cls):
        # Arrange / Act
        provider = resolve_provider()

        # Assert
        self.assertIs(provider, bedrock_cls.return_value)
        bedrock_cls.assert_called_once_with(model_id="us.anthropic.claude-opus-5")
