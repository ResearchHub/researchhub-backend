from django.test import SimpleTestCase, override_settings

from research_ai.services import llm_models
from research_ai.services.agent.model_capabilities import model_capabilities
from research_ai.services.agent.model_pricing import model_pricing
from research_ai.services.agent.providers.registry import split_model_ref
from research_ai.services.llm_models import (
    CLAUDE_PLATFORM_AGENT,
    PEER_REVIEW,
    ROLES,
    refusal_fallback_ref,
)


class ModelRoleTests(SimpleTestCase):
    def test_every_role_names_a_reviewed_model(self):
        # Act / Assert: callers read controls and ceilings from capabilities.
        for role in ROLES:
            with self.subTest(role=role):
                capabilities = model_capabilities(role.provider, role.default)
                self.assertIsNotNone(capabilities.max_output_tokens)

    def test_billed_defaults_have_reviewed_pricing(self):
        # Arrange
        fallback_provider, fallback_model = split_model_ref(llm_models.REFUSAL_FALLBACK)
        billed = (
            (CLAUDE_PLATFORM_AGENT.provider, CLAUDE_PLATFORM_AGENT.default),
            (fallback_provider, fallback_model),
        )

        # Act / Assert
        for provider, model_id in billed:
            with self.subTest(model=f"{provider}:{model_id}"):
                self.assertIsNotNone(model_pricing(provider, model_id))

    @override_settings(AI_PEER_REVIEW_BEDROCK_MODEL_ID="us.anthropic.claude-x")
    def test_setting_overrides_the_default(self):
        # Act / Assert
        self.assertEqual(PEER_REVIEW.model_id, "us.anthropic.claude-x")

    @override_settings(AI_PEER_REVIEW_BEDROCK_MODEL_ID="")
    def test_empty_setting_keeps_the_default(self):
        # Act / Assert
        self.assertEqual(PEER_REVIEW.model_id, PEER_REVIEW.default)


class RefusalFallbackRefTests(SimpleTestCase):
    @override_settings(RESEARCH_AI_REFUSAL_FALLBACK_MODEL=None)
    def test_unset_setting_uses_the_default(self):
        # Act / Assert
        self.assertEqual(refusal_fallback_ref(), llm_models.REFUSAL_FALLBACK)

    @override_settings(RESEARCH_AI_REFUSAL_FALLBACK_MODEL="")
    def test_empty_setting_turns_moves_off(self):
        # Act / Assert
        self.assertIsNone(refusal_fallback_ref())

    @override_settings(RESEARCH_AI_REFUSAL_FALLBACK_MODEL="openrouter:x/y")
    def test_setting_overrides_the_default(self):
        # Act / Assert
        self.assertEqual(refusal_fallback_ref(), "openrouter:x/y")
