from django.test import SimpleTestCase

from research_ai.constants import ExpertiseLevel, Gender, Region
from research_ai.prompts.expert_finder_prompts import (
    build_user_prompt,
    format_additional_context_section,
)


class FormatAdditionalContextSectionTests(SimpleTestCase):
    def test_empty_none_whitespace_returns_empty(self):
        self.assertEqual(format_additional_context_section(None), "")
        self.assertEqual(format_additional_context_section(""), "")
        self.assertEqual(format_additional_context_section("   \n"), "")

    def test_non_empty_includes_heading_and_body(self):
        s = format_additional_context_section("Prefer EU-based PIs.")
        self.assertIn("## Additional guidance from the requester", s)
        self.assertIn("Prefer EU-based PIs.", s)

    def test_braces_in_user_text_do_not_break_section(self):
        s = format_additional_context_section("Use {foo} syntax freely.")
        self.assertIn("{foo}", s)


class BuildUserPromptAdditionalContextTests(SimpleTestCase):
    def test_query_prompt_without_additional_context_no_extra_heading(self):
        out = build_user_prompt(
            query="Abstract here.",
            expert_count=5,
            expertise_level=[ExpertiseLevel.ALL_LEVELS],
            region_filter=Region.ALL_REGIONS,
            gender_filter=Gender.ALL_GENDERS,
            is_pdf=False,
            additional_context=None,
        )
        self.assertIn("Abstract here.", out)
        self.assertNotIn("Additional guidance from the requester", out)

    def test_query_prompt_with_additional_context_inserts_section(self):
        out = build_user_prompt(
            query="RFP body.",
            expert_count=5,
            expertise_level=[ExpertiseLevel.ALL_LEVELS],
            region_filter=Region.ALL_REGIONS,
            gender_filter=Gender.ALL_GENDERS,
            is_pdf=False,
            additional_context="Focus on structural biology.",
        )
        self.assertIn("RFP body.", out)
        self.assertIn("Additional guidance from the requester", out)
        self.assertIn("Focus on structural biology.", out)
        self.assertLess(out.index("RFP body."), out.index("Additional guidance"))

    def test_pdf_prompt_with_additional_context(self):
        out = build_user_prompt(
            query="Paper text.",
            expert_count=3,
            expertise_level=[ExpertiseLevel.ALL_LEVELS],
            region_filter=Region.ALL_REGIONS,
            gender_filter=Gender.ALL_GENDERS,
            is_pdf=True,
            additional_context="Prioritize junior faculty.",
        )
        self.assertIn("Paper text.", out)
        self.assertIn("Prioritize junior faculty.", out)
