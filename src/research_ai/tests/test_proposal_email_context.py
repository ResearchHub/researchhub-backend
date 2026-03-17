"""Tests for research_ai.services.proposal_email_context."""

from unittest.mock import MagicMock

from django.test import TestCase

from research_ai.services.proposal_email_context import (
    build_proposal_context,
    get_proposal_frontend_url,
)


class GetProposalFrontendUrlTests(TestCase):
    def test_returns_none_when_none(self):
        self.assertIsNone(get_proposal_frontend_url(None))

    def test_returns_url_from_unified_document_frontend_view_link(self):
        udoc = MagicMock()
        udoc.unified_document = udoc  # so getattr returns same object with frontend_view_link
        udoc.frontend_view_link.return_value = (
            "https://www.researchhub.com/post/10/my-slug"
        )
        url = get_proposal_frontend_url(udoc)
        self.assertEqual(url, "https://www.researchhub.com/post/10/my-slug")

    def test_returns_url_from_post_id_slug_when_no_frontend_view_link(self):
        post = MagicMock()
        post.unified_document = None
        post.id = 5
        post.slug = "prereg-2025"
        url = get_proposal_frontend_url(post)
        self.assertIn("/post/5/prereg-2025", url)


class BuildProposalContextTests(TestCase):
    def test_returns_empty_dict_when_none(self):
        self.assertEqual(build_proposal_context(None), {})

    def test_returns_title_url_created_by_blurb_from_post(self):
        post = MagicMock()
        post.title = "My Preregistration"
        post.renderable_text = "Body text here."
        post.created_by = None
        post.unified_document = MagicMock()
        post.unified_document.fundraises.first.return_value = None
        post.unified_document.frontend_view_link.return_value = (
            "https://www.researchhub.com/post/1/slug"
        )
        result = build_proposal_context(post)
        self.assertEqual(result["title"], "My Preregistration")
        self.assertEqual(result["url"], "https://www.researchhub.com/post/1/slug")
        self.assertEqual(result["created_by_name"], "")
        self.assertEqual(result["blurb"], "Body text here.")
        self.assertEqual(result["goal_amount"], "")
        self.assertEqual(result["amount_raised"], "")
        self.assertEqual(result["contributor_count"], "")
        self.assertEqual(result["deadline"], "")

    def test_returns_created_by_name_when_set(self):
        post = MagicMock()
        post.title = "Proposal"
        post.renderable_text = ""
        creator = MagicMock()
        creator.first_name = "Jane"
        creator.last_name = "Doe"
        creator.email = "jane@example.com"
        post.created_by = creator
        post.unified_document = MagicMock()
        post.unified_document.fundraises.first.return_value = None
        post.unified_document.frontend_view_link.return_value = (
            "https://x.com/post/1/s"
        )
        result = build_proposal_context(post)
        self.assertEqual(result["created_by_name"], "Jane Doe")
