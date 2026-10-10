from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase

from research_ai.services.agent import model_pricing as pricing_module
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

    def test_new_model_prices_and_long_context_rates(self):
        # Arrange
        cases = (
            ("claude_platform", "claude-opus-5-5", 2_400_000),
            ("openrouter", "openai/gpt-6-sol", 1_200_000),
            ("openrouter", "openai/gpt-6-luna", 60_000),
            ("openrouter", "qwen/qwen3.8-max-0902", 800_000),
        )

        # Act / Assert
        for provider, model_id, expected in cases:
            with self.subTest(model_id=model_id):
                usage = TurnUsage(input_tokens=100_000, output_tokens=100_000)
                self.assertEqual(cost_microusd(provider, model_id, usage), expected)

        # Long-context pricing applies to the full GPT-6 request.
        usage = TurnUsage(input_tokens=272_001, output_tokens=1_000)
        self.assertEqual(
            cost_microusd("openrouter", "openai/gpt-6-luna", usage), 55_150
        )

    def test_open_weight_models_use_openrouter_list_prices(self):
        # Arrange
        usage = TurnUsage(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cache_read_tokens=1_000_000,
        )
        cases = (
            # $0.80 input, $15 output, $0.55 cached input.
            ("moonshotai/kimi-k3", 16_350_000),
            # $0.0055 input, $1.28 output, $0.0055 cached input.
            ("deepseek/deepseek-v4-flash-0731", 1_291_000),
        )

        # Act / Assert
        for model_id, expected in cases:
            with self.subTest(model_id=model_id):
                self.assertEqual(cost_microusd("openrouter", model_id, usage), expected)

    def test_gemini_3_8_flash_web_search_requests_are_priced(self):
        # Arrange
        usage = TurnUsage(web_search_requests=2)

        # Act
        cost = cost_microusd("openrouter", "google/gemini-3.8-flash", usage)

        # Assert: OpenRouter lists $0.014 per search.
        self.assertEqual(cost, 28_000)

    def test_opus_5_5_cache_reads_use_its_model_specific_rate(self):
        # Arrange
        usage = TurnUsage(cache_read_tokens=1_000_000)

        # Act
        cost = cost_microusd("claude_platform", "claude-opus-5-5", usage)

        # Assert: Claude lists $0.20 per million cached input tokens.
        self.assertEqual(cost, 200_000)

    def test_unpriced_model_returns_none(self):
        self.assertIsNone(cost_microusd("openrouter", "unknown/model", TurnUsage(1, 1)))

    def test_claude_web_search_requests_add_one_cent_each(self):
        # Arrange
        usage = TurnUsage(web_search_requests=2)

        # Act
        cost = cost_microusd("claude_platform", "claude-opus-5", usage)

        # Assert
        self.assertEqual(cost, 20_000)

    def test_baseline_model_is_one_x(self):
        # Arrange / Act / Assert
        self.assertEqual(
            cost_multiplier("claude_platform:claude-opus-5-5"),
            Decimal("1.0"),
        )

    def test_multiplier_is_relative_to_baseline_model(self):
        # Arrange / Act / Assert
        self.assertEqual(
            cost_multiplier("openrouter:deepseek/deepseek-v4-pro-0813"),
            Decimal("0.11"),
        )

    def test_low_cost_model_multiplier_does_not_round_to_zero(self):
        # Arrange / Act
        multiplier = cost_multiplier("openrouter:deepseek/deepseek-v4-flash-0731")

        # Assert
        self.assertEqual(multiplier, Decimal("0.05"))

    def test_new_cheaper_model_does_not_change_existing_multipliers(self):
        # Arrange
        cheaper = pricing_module.ModelPricing(*(Decimal("0.001"),) * 5)

        # Act
        with patch.dict(pricing_module._OPENROUTER_PRICING, {"new/model": cheaper}):
            multiplier = cost_multiplier("openrouter:deepseek/deepseek-v4-pro-0813")

        # Assert
        self.assertEqual(multiplier, Decimal("0.11"))
