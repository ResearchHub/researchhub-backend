from decimal import Decimal
from unittest import TestCase

from research_ai.services.agent.model_pricing import cost_microusd
from research_ai.services.agent.types import TurnUsage
from research_ai.services.credit_service import (
    credits_from_microusd,
    model_credit_rates,
)


class CreditServiceTests(TestCase):
    def test_conversion_preserves_fractional_credits_and_unknown_amounts(self):
        # Arrange
        cases = [(None, None), (0, "0"), (1, "0.001"), (250_000, "250")]

        # Act / Assert
        for amount, expected in cases:
            with self.subTest(amount=amount):
                self.assertEqual(credits_from_microusd(amount), expected)

    def test_displayed_rates_match_recorded_cost_including_cache_and_search(self):
        # Arrange
        rates = model_credit_rates("claude_platform:claude-opus-5")
        usage = TurnUsage(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cache_read_tokens=1_000_000,
            cache_write_tokens=1_000_000,
            web_search_requests=1,
        )

        # Act
        recorded = credits_from_microusd(
            cost_microusd("claude_platform", "claude-opus-5", usage)
        )
        displayed = sum(Decimal(rate) for rate in rates.values())

        # Assert
        self.assertEqual(displayed, Decimal(recorded))
        self.assertEqual(displayed, Decimal(36760))

    def test_unpriced_model_has_unknown_credit_rates(self):
        # Arrange / Act
        rates = model_credit_rates("openrouter:unknown/model")

        # Assert
        self.assertIsNone(rates)

    def test_long_context_rates_match_fallback_cost_above_threshold(self):
        # Arrange
        rates = model_credit_rates("openrouter:openai/gpt-5.6-sol")
        override = rates["long_context"]
        usage = TurnUsage(input_tokens=272_001, output_tokens=1000)

        # Act
        recorded = credits_from_microusd(
            cost_microusd("openrouter", "openai/gpt-5.6-sol", usage)
        )
        displayed = (
            Decimal(override["credit_rates"]["input_per_million_tokens"])
            * usage.input_tokens
            + Decimal(override["credit_rates"]["output_per_million_tokens"])
            * usage.output_tokens
        ) / 1_000_000

        # Assert
        self.assertEqual(override["prompt_tokens_above"], 272_000)
        self.assertEqual(displayed, Decimal(recorded))

    def test_credits_use_provider_reported_cost_when_available(self):
        # Arrange
        usage = TurnUsage(input_tokens=1_000_000, provider_cost_microusd=123)

        # Act
        credits = credits_from_microusd(
            cost_microusd("openrouter", "openai/gpt-5.6-sol", usage)
        )

        # Assert
        self.assertEqual(credits, "0.123")
