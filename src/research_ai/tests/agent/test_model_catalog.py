"""Unit tests for the user-selectable model catalog (no network calls)."""

from django.test import SimpleTestCase, override_settings

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
