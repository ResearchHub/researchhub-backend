"""Unit tests for frontend generation-option parsing (no database calls)."""

from django.test import SimpleTestCase

from research_ai.serializers import ProposalDraftCreateSerializer


class GenerationOptionsSerializerTests(SimpleTestCase):
    def test_rejects_non_finite_temperature_values(self):
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value):
                # Arrange
                serializer = ProposalDraftCreateSerializer(
                    data={"search_expert_id": 1, "temperature": value}
                )

                # Act
                valid = serializer.is_valid()

                # Assert
                self.assertFalse(valid)
                self.assertEqual(
                    serializer.errors["temperature"],
                    ["A finite number is required."],
                )
