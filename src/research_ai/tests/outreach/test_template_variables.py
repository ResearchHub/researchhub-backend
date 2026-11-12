"""
Tests for email_template_variables: build_replacement_context and
replace_template_variables.
"""

from unittest.mock import MagicMock

from django.test import TestCase

from research_ai.services.outreach.template_variables import (
    build_replacement_context,
    format_expert_name_from_raw,
    replace_template_variables,
)


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
