from django.test import SimpleTestCase

from research_ai.services import llm_models
from research_ai.services.agent.model_capabilities import model_capabilities
from research_ai.services.agent.model_pricing import model_pricing
from research_ai.services.agent.providers.registry import split_model_ref
from research_ai.services.llm_models import CLAUDE_PLATFORM_AGENT, ROLES


class ModelRoleTests(SimpleTestCase):
    def test_every_role_names_a_reviewed_model(self):
        # Act / Assert: callers read controls and ceilings from capabilities.
        for role in ROLES:
            with self.subTest(role=role):
                capabilities = model_capabilities(role.provider, role.model_id)
                self.assertIsNotNone(capabilities.max_output_tokens)

    def test_billed_defaults_have_reviewed_pricing(self):
        # Arrange
        fallback_provider, fallback_model = split_model_ref(llm_models.REFUSAL_FALLBACK)
        billed = (
            (CLAUDE_PLATFORM_AGENT.provider, CLAUDE_PLATFORM_AGENT.model_id),
            (fallback_provider, fallback_model),
        )

        # Act / Assert
        for provider, model_id in billed:
            with self.subTest(model=f"{provider}:{model_id}"):
                self.assertIsNotNone(model_pricing(provider, model_id))
