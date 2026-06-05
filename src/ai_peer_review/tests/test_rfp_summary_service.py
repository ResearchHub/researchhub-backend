from unittest.mock import MagicMock

from django.test import SimpleTestCase

from ai_peer_review.services.rfp_summary_service import get_grant_source_text


class GetGrantSourceTextTests(SimpleTestCase):
    def test_combines_metadata_and_post_markdown(self):
        grant = MagicMock()
        grant.short_title = "My RFP"
        grant.organization = "NIH"
        grant.description = "Do good science."
        post = MagicMock()
        post.get_full_markdown.return_value = "# Details\nMore"
        grant.unified_document.posts.first.return_value = post

        text = get_grant_source_text(grant)

        self.assertIn("My RFP", text)
        self.assertIn("NIH", text)
        self.assertIn("Do good science.", text)
        self.assertIn("# Details", text)

    def test_handles_missing_post(self):
        grant = MagicMock()
        grant.short_title = None
        grant.organization = None
        grant.description = "Solo body"
        grant.unified_document.posts.first.return_value = None

        self.assertEqual(get_grant_source_text(grant).strip(), "Solo body")
