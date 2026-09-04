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

    def test_provider_reported_cost_takes_precedence_over_static_price(self):
        # Arrange
        usage = TurnUsage(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            provider_cost_microusd=123,
        )

        # Act
        cost = cost_microusd("openrouter", "openai/gpt-5.6-sol", usage)

        # Assert
        self.assertEqual(cost, 123)

    def test_openrouter_long_context_override_is_used_as_fallback(self):
        # Arrange
        usage = TurnUsage(input_tokens=272_001, output_tokens=1_000)

        # Act
        cost = cost_microusd("openrouter", "openai/gpt-5.6-sol", usage)

        # Assert
        self.assertEqual(cost, 1_103_004)

    def test_openrouter_threshold_is_strictly_greater_than(self):
        # Arrange
        usage = TurnUsage(input_tokens=272_000, output_tokens=1_000)

        # Act
        cost = cost_microusd("openrouter", "openai/gpt-5.6-sol", usage)

        # Assert
        self.assertEqual(cost, 554_000)

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
            cost_multiplier("openrouter:deepseek/deepseek-v4-flash-0731"),
            Decimal("1.0"),
        )

    def test_multiplier_is_relative_to_cheapest_catalog_model(self):
        self.assertEqual(
            cost_multiplier("openrouter:deepseek/deepseek-v4-pro-0813"),
            Decimal("12.6"),
        )
