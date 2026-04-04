from django.test import SimpleTestCase

from ai_peer_review.prompts.proposal_review_prompts import (
    build_proposal_review_user_prompt,
    get_openai_web_context_system_prompt,
)


class ProposalReviewUserPromptTests(SimpleTestCase):
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
        self.assertIn("OpenAlex stats here", text)

    def test_includes_web_search_context_when_provided(self):
        text = build_proposal_review_user_prompt(
            "My proposal",
            web_search_context="- note with https://example.com",
        )
        self.assertIn("WEB SEARCH NOTES", text)
        self.assertIn("https://example.com", text)
