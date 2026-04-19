from django.test import SimpleTestCase

from ai_peer_review.prompts.proposal_review_prompts import (
    build_proposal_review_user_prompt,
    get_openai_web_context_system_prompt,
    get_proposal_review_system_prompt,
)
from ai_peer_review.prompts.rfp_summary_prompts import (
    build_rfp_summary_user_prompt,
    get_grant_executive_summary_system_prompt,
    get_rfp_summary_system_prompt,
)


class ProposalReviewUserPromptTests(SimpleTestCase):
    def test_proposal_review_system_prompt_loads(self):
        text = get_proposal_review_system_prompt()
        self.assertIn("expert scientific grant reviewer", text)
        self.assertIn("OUTPUT JSON SHAPE", text)
        self.assertIn("funding_opportunity_fit", text)
        self.assertIn("Critical fail cap rule", text)
        self.assertIn("descending importance", text)

    def test_user_prompt_requests_strengths_weaknesses_order(self):
        text = build_proposal_review_user_prompt("Body")
        self.assertIn("most important items", text)
        self.assertIn("first in each array", text)

    def test_openai_web_context_system_prompt_loads(self):
        text = get_openai_web_context_system_prompt()
        self.assertIn("web-grounded", text)
        self.assertIn("No additional web context", text)

    def test_includes_external_researcher_context_when_provided(self):
        text = build_proposal_review_user_prompt(
            "My proposal",
            external_researcher_context="OpenAlex stats here",
        )
        self.assertIn("EXTERNAL RESEARCHER CONTEXT", text)
        self.assertIn("feasibility_and_execution.team_environment", text)
        self.assertIn("OpenAlex stats here", text)

    def test_includes_web_search_context_when_provided(self):
        text = build_proposal_review_user_prompt(
            "My proposal",
            web_search_context="- note with https://example.com",
        )
        self.assertIn("WEB SEARCH NOTES", text)
        self.assertIn("https://example.com", text)


class RfpSummaryPromptTests(SimpleTestCase):
    def test_rfp_summary_system_prompt_loads(self):
        text = get_rfp_summary_system_prompt()
        self.assertIn("grant strategy analyst", text)

    def test_grant_executive_summary_system_prompt_loads(self):
        text = get_grant_executive_summary_system_prompt()
        self.assertIn("funding program officer", text)

    def test_build_rfp_summary_user_prompt(self):
        text = build_rfp_summary_user_prompt("  Hello RFP  ")
        self.assertIn("Hello RFP", text)
        self.assertTrue(text.startswith("Summarize the following RFP"))
