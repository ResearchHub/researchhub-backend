from decimal import Decimal

from django.test import SimpleTestCase

from research_ai.services.agent.model_pricing import cost_microusd, cost_multiplier
from research_ai.services.agent.types import TurnUsage


class ModelPricingTests(SimpleTestCase):
    def test_prices_all_four_usage_buckets_in_microusd(self):
        # Arrange
        usage = TurnUsage(1_000_000, 1_000_000, 1_000_000, 1_000_000)

        # Act
        cost = cost_microusd("openrouter", "deepseek/deepseek-v4-pro-0813", usage)

        # Assert
        self.assertEqual(cost, 3_322_000)

    def test_unpriced_model_returns_none(self):
        self.assertIsNone(cost_microusd("openrouter", "unknown/model", TurnUsage(1, 1)))

    def test_claude_web_search_requests_add_one_cent_each(self):
        # Arrange
        usage = TurnUsage(web_search_requests=2)

        # Act
        cost = cost_microusd("claude_platform", "claude-opus-5", usage)

        # Assert
        self.assertEqual(cost, 20_000)

    def test_cheapest_catalog_model_is_one_x(self):
        self.assertEqual(
            cost_multiplier("openrouter:openai/gpt-5.6-luna"),
            Decimal("1.0"),
        )

    def test_multiplier_is_relative_to_cheapest_catalog_model(self):
        self.assertEqual(
            cost_multiplier("openrouter:deepseek/deepseek-v4-pro-0813"),
            Decimal("1.9"),
        )
