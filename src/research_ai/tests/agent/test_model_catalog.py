"""Unit tests for the user-selectable model catalog (no network calls)."""

from django.test import SimpleTestCase, override_settings

from research_ai.services.agent.model_capabilities import validate_generation_options
from research_ai.services.agent.model_catalog import (
    available_models,
    default_model_ref,
    validate_model_ref,
)

# Every provider credential present, so the whole catalog is listed.
ALL_PROVIDERS_CONFIGURED = {
    "ANTHROPIC_AWS_WORKSPACE_ID": "ws-test",
    "AWS_REGION_NAME": "us-east-1",
    "OPENROUTER_API_KEY": "or-test",
}


@override_settings(**ALL_PROVIDERS_CONFIGURED)
class AvailableModelsTests(SimpleTestCase):
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

    def test_haiku_advertises_temperature_but_not_effort_or_thinking(self):
        # Arrange
        option = next(
            option
            for option in available_models()
            if option.ref == "claude_platform:claude-haiku-4-5"
        )

        # Act
        capabilities = option.capabilities

        # Assert
        self.assertEqual(capabilities.effort, ())
        self.assertEqual(capabilities.thinking, ())
        self.assertTrue(capabilities.temperature)

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

    @override_settings(OPENROUTER_API_KEY="")
    def test_unconfigured_provider_models_are_hidden(self):
        # Act
        options = available_models()

        # Assert
        self.assertTrue(options)
        self.assertFalse(any(o.provider == "openrouter" for o in options))

    @override_settings(ANTHROPIC_AWS_WORKSPACE_ID="")
    def test_generator_default_is_always_selectable(self):
        # Arrange: the default generator's provider has no credentials, so its
        # catalog entries are hidden -- but the default itself must survive.
        default = default_model_ref()

        # Act
        options = available_models()

        # Assert
        self.assertEqual(options[0].ref, default)
        self.assertNotIn(
            "claude_platform:claude-sonnet-5", [option.ref for option in options]
        )


@override_settings(**ALL_PROVIDERS_CONFIGURED)
class ValidateModelRefTests(SimpleTestCase):
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

    @override_settings(OPENROUTER_API_KEY="")
    def test_model_on_unconfigured_provider_is_rejected(self):
        # Act / Assert
        with self.assertRaises(ValueError):
            validate_model_ref("openrouter:openai/gpt-5.6-sol")


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
