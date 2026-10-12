from django.test import SimpleTestCase

from research_ai.prompts.expert_finder_prompts import (
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
