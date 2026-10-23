from decimal import Decimal
from unittest import TestCase

from research_ai.prompts.cover_image_prompts import CoverImagePrompts


class FormatUsdCompactTests(TestCase):
    def test_formats_amounts_compactly(self):
        cases = {
            Decimal(900): "$900",
            Decimal(23000): "$23K",
            Decimal(12500): "$12.5K",
            Decimal(1500000): "$1.5M",
            Decimal(2000000): "$2M",
        }
        for amount, expected in cases.items():
            with self.subTest(amount=amount):
                # Act
                formatted = CoverImagePrompts.format_usd_compact(amount)

                # Assert
                self.assertEqual(formatted, expected)


class BuildCoverImagePromptsTests(TestCase):
    def test_rfp_prompts_show_label_title_funding_subtitle_and_organization(self):
        # Act
        prompts = CoverImagePrompts.build(
            document_type="GRANT",
            title="Epothilone B and anesthetic sensitivity",
            subtitle="Independent replication in rodents & Tetrahymena",
            organization="Athanatos Foundation",
            funding_amount_usd=Decimal(23000),
        )

        # Assert
        self.assertEqual(len(prompts), CoverImagePrompts.VARIANT_COUNT)
        self.assertEqual(len(set(prompts)), CoverImagePrompts.VARIANT_COUNT)
        for prompt in prompts:
            self.assertIn('"REQUEST FOR PROPOSALS"', prompt)
            self.assertIn('"Epothilone B and anesthetic sensitivity"', prompt)
            self.assertIn('"Up to $23K in funding"', prompt)
            self.assertIn('"Independent replication in rodents & Tetrahymena"', prompt)
            self.assertIn('"Athanatos Foundation"', prompt)

    def test_proposal_prompts_ask_for_funding_without_an_organization(self):
        # Act
        prompts = CoverImagePrompts.build(
            document_type="PREREGISTRATION",
            title="A study",
            funding_amount_usd=Decimal(5000),
        )

        # Assert
        for prompt in prompts:
            self.assertIn('"RESEARCH PROPOSAL"', prompt)
            self.assertIn('"Seeking $5K in funding"', prompt)
            self.assertNotIn("organization name", prompt)

    def test_leaves_out_missing_funding_and_a_long_subtitle(self):
        # Act
        prompts = CoverImagePrompts.build(
            document_type="GRANT",
            title="A study",
            subtitle="x" * (CoverImagePrompts.MAX_SUBTITLE_CHARS + 1),
        )

        # Assert
        for prompt in prompts:
            self.assertNotIn("in funding", prompt)
            self.assertNotIn("subtitle", prompt)

    def test_user_text_cannot_break_out_of_its_quotes(self):
        # Act
        prompts = CoverImagePrompts.build(
            document_type="GRANT", title='The "best"\nstudy {title}'
        )

        # Assert
        self.assertIn("\"The 'best' study {title}\"", prompts[0])

    def test_leaves_the_colors_to_the_model(self):
        # Act
        prompts = CoverImagePrompts.build(
            document_type="GRANT", title="A study", organization="A Foundation"
        )

        # Assert
        for prompt in prompts:
            self.assertNotRegex(prompt, r"#[0-9A-Fa-f]{6}")
            for color in ("gold", "white", "charcoal", "black", "navy"):
                self.assertNotIn(color, prompt.lower())

    def test_never_asks_for_an_organization_logo(self):
        for organization in ("Athanatos Foundation", ""):
            with self.subTest(organization=organization):
                # Act
                prompts = CoverImagePrompts.build(
                    document_type="GRANT", title="A study", organization=organization
                )

                # Assert
                for prompt in prompts:
                    self.assertIn("Never draw a logo", prompt)
                    self.assertNotRegex(prompt, r"(?i)\barcs?\b")

    def test_with_a_logo_asks_to_reproduce_it_exactly(self):
        # Act
        prompts = CoverImagePrompts.build(
            document_type="GRANT",
            title="A study",
            organization="Athanatos Foundation",
            has_logo=True,
        )

        # Assert
        self.assertEqual(len(prompts), CoverImagePrompts.VARIANT_COUNT)
        for prompt in prompts:
            self.assertIn("the provided logo, reproduced exactly", prompt)
            self.assertIn("Reproduce it faithfully", prompt)
            self.assertNotIn("Never draw a logo", prompt)
