"""Tests for email_template_variables: build_replacement_context and replace_template_variables."""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from research_ai.services.email_template_variables import (
    build_replacement_context,
    format_expert_name_from_raw,
    replace_template_variables,
)
from research_ai.services.rfp_email_context import build_rfp_context


class ReplaceTemplateVariablesTests(TestCase):
    def test_replaces_user_variables(self):
        context = {
            "user": {
                "email": "u@x.com",
                "full_name": "Jane Doe",
                "name": "Jane Doe",
                "headline": "Prof",
                "organization": "MIT",
            },
            "rfp": {},
            "expert": {},
        }
        text = (
            "Hello, {{user.name}}. Email: {{user.email}}. Org: {{user.organization}}."
        )
        out = replace_template_variables(text, context)
        self.assertEqual(out, "Hello, Jane Doe. Email: u@x.com. Org: MIT.")

    def test_replaces_rfp_variables(self):
        context = {
            "user": {},
            "rfp": {
                "title": "Grant X",
                "deadline": "May 1",
                "blurb": "Desc",
                "amount": "$10K",
                "url": "https://x.com",
            },
            "expert": {},
        }
        text = "See {{rfp.title}} ({{rfp.amount}}), due {{rfp.deadline}}. {{rfp.url}}"
        out = replace_template_variables(text, context)
        self.assertIn("Grant X", out)
        self.assertIn("$10K", out)
        self.assertIn("May 1", out)
        self.assertIn("https://x.com", out)

    def test_replaces_expert_variables(self):
        context = {
            "user": {},
            "rfp": {},
            "expert": {
                "name": "Dr. Y",
                "title": "Prof",
                "affiliation": "Stanford",
                "email": "y@stanford.edu",
                "expertise": "ML",
            },
        }
        text = "Dear {{expert.name}}, {{expert.title}} at {{expert.affiliation}}."
        out = replace_template_variables(text, context)
        self.assertEqual(out, "Dear Dr. Y, Prof at Stanford.")

    def test_replaces_proposal_variables(self):
        context = {
            "user": {},
            "rfp": {},
            "proposal": {
                "title": "Replication Study 2025",
                "url": "https://www.researchhub.com/post/1/my-prereg",
                "created_by_name": "Jane Doe",
                "goal_amount": "$10K",
                "amount_raised": "$2K",
                "contributor_count": "5",
                "deadline": "April 1, 2026",
                "blurb": "We plan to replicate...",
            },
            "expert": {},
        }
        text = "Check out {{proposal.title}} by {{proposal.created_by_name}}. {{proposal.amount_raised}} of {{proposal.goal_amount}}."
        out = replace_template_variables(text, context)
        self.assertIn("Replication Study 2025", out)
        self.assertIn("Jane Doe", out)
        self.assertIn("$2K", out)
        self.assertIn("$10K", out)

    def test_unknown_entity_or_field_replaced_with_empty(self):
        context = {"user": {"name": "J"}, "rfp": {}, "expert": {}}
        text = "{{user.name}} {{unknown.foo}} {{user.missing}}"
        out = replace_template_variables(text, context)
        self.assertEqual(out, "J  ")

    def test_empty_text_returns_empty(self):
        self.assertEqual(replace_template_variables("", {}), "")
        self.assertEqual(
            replace_template_variables("", {"user": {}, "rfp": {}, "expert": {}}), ""
        )


class BuildReplacementContextTests(TestCase):
    def test_build_replacement_context_fills_user_rfp_expert(self):
        user = MagicMock()
        user.email = "sender@x.com"
        user.first_name = "Alice"
        user.last_name = "Smith"
        user.author_profile.headline = "Editor"
        user.organization = None
        rfp_dict = {
            "title": "RFP A",
            "deadline": "Jun 1",
            "blurb": "B",
            "amount": "$5K",
            "url": "https://r.com",
        }
        expert_dict = {
            "name": "Bob",
            "title": "Dr",
            "affiliation": "Yale",
            "email": "bob@yale.edu",
            "expertise": "Bio",
        }
        ctx = build_replacement_context(
            user=user,
            rfp_context_dict=rfp_dict,
            resolved_expert=expert_dict,
        )
        self.assertEqual(ctx["user"]["email"], "sender@x.com")
        self.assertEqual(ctx["user"]["full_name"], "Alice Smith")
        self.assertEqual(ctx["user"]["headline"], "Editor")
        self.assertEqual(ctx["rfp"]["title"], "RFP A")
        self.assertEqual(ctx["rfp"]["blurb"], "B")
        self.assertEqual(ctx["expert"]["name"], "Bob")
        self.assertEqual(ctx["expert"]["affiliation"], "Yale")

    def test_build_replacement_context_expert_name_uses_structured_parts(self):
        expert_dict = {
            "name": "Dr. Jane Q. Doe, PhD",
            "honorific": "Dr",
            "first_name": "Jane",
            "middle_name": "Q.",
            "last_name": "Doe",
            "academic_title": "Professor",
            "affiliation": "MIT",
            "email": "j@mit.edu",
            "expertise": "AI",
        }
        ctx = build_replacement_context(resolved_expert=expert_dict)
        self.assertEqual(ctx["expert"]["name"], "Dr. Jane Q. Doe")
        self.assertEqual(ctx["expert"]["title"], "Professor")

    def test_none_inputs_yield_empty_entity_dicts(self):
        ctx = build_replacement_context(
            user=None,
            rfp_context_dict=None,
            proposal_context_dict=None,
            resolved_expert=None,
        )
        self.assertEqual(ctx["user"]["full_name"], "")
        self.assertEqual(ctx["rfp"]["title"], "")
        self.assertEqual(ctx["proposal"]["title"], "")
        self.assertEqual(ctx["expert"]["name"], "")

    def test_format_expert_name_first_and_last_token_only(self):
        self.assertEqual(
            format_expert_name_from_raw("Dr. Jane Marie Smith"),
            "Dr. Smith",
        )

    def test_format_expert_name_drops_middle_initial(self):
        self.assertEqual(format_expert_name_from_raw("John F. Kennedy"), "John Kennedy")

    def test_format_expert_name_two_tokens_unchanged(self):
        self.assertEqual(format_expert_name_from_raw("Jane Smith"), "Jane Smith")

    def test_build_replacement_context_fills_proposal_when_provided(self):
        proposal_dict = {
            "title": "My Preregistration",
            "url": "https://www.researchhub.com/post/1/slug",
            "created_by_name": "Alice",
            "goal_amount": "$5K",
            "amount_raised": "$1K",
            "contributor_count": "3",
            "deadline": "May 1, 2026",
            "blurb": "Short blurb.",
        }
        ctx = build_replacement_context(proposal_context_dict=proposal_dict)
        self.assertEqual(ctx["proposal"]["title"], "My Preregistration")
        self.assertEqual(
            ctx["proposal"]["url"], "https://www.researchhub.com/post/1/slug"
        )
        self.assertEqual(ctx["proposal"]["created_by_name"], "Alice")
        self.assertEqual(ctx["proposal"]["amount_raised"], "$1K")
        self.assertEqual(ctx["proposal"]["contributor_count"], "3")


class BuildRfpContextBlurbTests(TestCase):
    """Assert build_rfp_context returns blurb key (alias for description_snippet)."""

    @patch("research_ai.services.rfp_email_context.get_grant_frontend_url")
    def test_build_rfp_context_includes_blurb_equal_to_description_snippet(
        self, mock_get_url
    ):
        mock_get_url.return_value = "https://www.researchhub.com/grant/1/test-slug"
        grant = MagicMock()
        grant.unified_document_id = 1
        grant.amount = 10_000
        grant.end_date = None
        grant.short_title = "Test Grant"
        grant.description = "Short description here."
        grant.unified_document.get_document.return_value = None
        result = build_rfp_context(grant, description_snippet_length=500)
        self.assertIn("blurb", result)
        self.assertIn("description_snippet", result)
        self.assertEqual(result["blurb"], result["description_snippet"])
        self.assertEqual(result["blurb"], "Short description here.")
