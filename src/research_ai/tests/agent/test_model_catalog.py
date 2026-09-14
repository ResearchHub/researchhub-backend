"""Unit tests for the user-selectable model catalog (no network calls)."""

from django.test import SimpleTestCase, override_settings

from research_ai.services.agent import model_catalog
from research_ai.services.agent.model_capabilities import (
    model_capabilities,
    validate_generation_options,
)
from research_ai.services.agent.model_catalog import (
    available_models,
    default_model_ref,
    validate_model_ref,
)
from research_ai.services.agent.model_pricing import model_pricing
from research_ai.services.agent.providers.registry import split_model_ref

# Provider keys live on the workers that run turns, not on the API process
# that serves the catalog, so every assertion below holds with none set.
NO_PROVIDER_CREDENTIALS = {
    "ANTHROPIC_AWS_WORKSPACE_ID": "",
    "AWS_REGION_NAME": "",
    "OPENROUTER_API_KEY": "",
}


@override_settings(**NO_PROVIDER_CREDENTIALS)
class AvailableModelsTests(SimpleTestCase):
    def test_every_catalog_model_has_reviewed_pricing(self):
        # Arrange
        options = model_catalog._CATALOG

        # Act
        unpriced = [
            option.ref
            for option in options
            if model_pricing(*split_model_ref(option.ref)) is None
        ]

        # Assert
        self.assertTrue(options)
        self.assertEqual(unpriced, [], "Add reviewed pricing for every catalog model")

    def test_catalog_refs_have_valid_structure(self):
        # Act
        options = available_models()

        # Assert
        for option in options:
            self.assertRegex(option.ref, r"^[^:\s]+:[^:\s]+$")
            if option.provider == "openrouter":
                self.assertRegex(option.ref, r"^[^:\s]+:[^/:\s]+/[^/:\s]+$")

    def test_every_option_carries_label_and_provider(self):
        # Act
        options = available_models()

        # Assert
        for option in options:
            self.assertTrue(option.label)
            self.assertIn(option.provider, ("bedrock", "claude_platform", "openrouter"))

    def test_every_catalog_model_declares_an_output_ceiling(self):
        # Arrange: both adapters refuse a model whose ceiling is unreviewed, so
        # a catalog entry without one cannot run a turn.
        options = available_models()

        # Act
        unreviewed = [
            option.ref
            for option in options
            if option.capabilities.max_output_tokens is None
        ]

        # Assert
        self.assertTrue(options)
        self.assertEqual(unreviewed, [])

    def test_openrouter_gpt_advertises_reasoning_but_not_temperature(self):
        # Arrange
        option = next(
            option
            for option in available_models()
            if option.ref == "openrouter:openai/gpt-5.6-sol"
        )

        # Act
        capabilities = option.capabilities

        # Assert
        self.assertIn("high", capabilities.effort)
        self.assertEqual(capabilities.thinking, ("adaptive", "disabled"))
        self.assertFalse(capabilities.temperature)

    @override_settings(RESEARCH_AI_GENERATOR_PROVIDER="bedrock")
    def test_generator_default_outside_the_catalog_is_still_listed(self):
        # Arrange: no Bedrock ref is catalogued, so the default is not one.
        default = default_model_ref()

        # Act
        options = available_models()

        # Assert
        self.assertEqual(default, "bedrock:us.anthropic.claude-opus-5")
        self.assertEqual(options[0].ref, default)


class CapabilityLookupTests(SimpleTestCase):
    def test_bedrock_haiku_carries_sampling_and_its_own_ceiling(self):
        # Act: the Converse adapter takes prefixed ids and exposes sampling only.
        capabilities = model_capabilities(
            "bedrock", "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        )

        # Assert
        self.assertTrue(capabilities.temperature)
        self.assertEqual(capabilities.effort, ())
        self.assertEqual(capabilities.thinking, ())
        self.assertEqual(capabilities.max_output_tokens, 64_000)

    def test_platform_decorations_resolve_to_the_same_model(self):
        # Arrange: dated snapshots and OpenRouter variant tags name one model.
        decorated = (
            ("claude_platform", "claude-haiku-4-5-20251001", 64_000),
            ("claude_platform", "claude-opus-4-5-20251101", 64_000),
            ("openrouter", "deepseek/deepseek-v4-pro-0813:free", 384_000),
        )

        # Act / Assert
        for provider, model_id, ceiling in decorated:
            with self.subTest(model_id=model_id):
                capabilities = model_capabilities(provider, model_id)
                self.assertEqual(capabilities.max_output_tokens, ceiling)

    def test_an_id_that_merely_contains_a_reviewed_id_is_unreviewed(self):
        # Arrange: a longer id is a different model, not the one it contains.
        near_misses = (
            ("claude_platform", "claude-opus-50"),
            ("claude_platform", "claude-haiku-4-50"),
            ("openrouter", "openai/gpt-5.6-sol-next"),
        )

        # Act / Assert
        for provider, model_id in near_misses:
            with self.subTest(model_id=model_id):
                self.assertIsNone(
                    model_capabilities(provider, model_id).max_output_tokens
                )

    def test_glm_flash_requires_reasoning(self):
        # Act
        capabilities = model_capabilities("openrouter", "z-ai/glm-5.3-flash")

        # Assert
        self.assertEqual(capabilities.effort, ("low", "high", "max"))
        self.assertEqual(capabilities.thinking, ("adaptive",))
        self.assertEqual(capabilities.max_output_tokens, 131_072)


@override_settings(**NO_PROVIDER_CREDENTIALS)
class ValidateModelRefTests(SimpleTestCase):
    @override_settings(RESEARCH_AI_GENERATOR_PROVIDER="bedrock")
    def test_unpriced_configured_default_cannot_be_selected(self):
        # Arrange
        default = default_model_ref()

        # Act / Assert
        with self.assertRaisesMessage(ValueError, "has no reviewed pricing"):
            validate_model_ref(default)

    def test_no_selection_returns_none(self):
        # Act / Assert
        self.assertIsNone(validate_model_ref(None))
        self.assertIsNone(validate_model_ref(""))
        self.assertIsNone(validate_model_ref("   "))

    def test_catalog_ref_is_returned_canonical(self):
        # Act / Assert
        self.assertEqual(
            validate_model_ref("claude_platform:claude-sonnet-5"),
            "claude_platform:claude-sonnet-5",
        )

    def test_bare_ref_canonicalizes_onto_generator_provider(self):
        # Act / Assert
        self.assertEqual(
            validate_model_ref("claude-opus-5"), "claude_platform:claude-opus-5"
        )

    def test_unknown_model_is_rejected(self):
        # Act / Assert
        with self.assertRaises(ValueError):
            validate_model_ref("openrouter:acme/totally-made-up")


class ValidateGenerationOptionsTests(SimpleTestCase):
    def test_temperature_requires_disabled_thinking_on_claude_4_6(self):
        # Act / Assert
        with self.assertRaisesRegex(ValueError, "requires thinking='disabled'"):
            validate_generation_options(
                "claude_platform",
                "claude-opus-4-6",
                temperature=0.4,
            )

    def test_openrouter_rejects_conflicting_reasoning_controls(self):
        # Act / Assert
        with self.assertRaisesRegex(ValueError, "cannot combine"):
            validate_generation_options(
                "openrouter",
                "openai/gpt-5.6-sol",
                effort="high",
                thinking="disabled",
            )
