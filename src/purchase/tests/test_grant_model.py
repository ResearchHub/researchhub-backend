from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

from django.test import SimpleTestCase, TestCase

from purchase.models import Grant
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import GRANT
from user.tests.helpers import create_random_authenticated_user


class GrantModelTests(TestCase):
    def setUp(self):
        # Create a moderator user
        self.user = create_random_authenticated_user("grant_model", moderator=True)

        # Create a grant post
        self.post = create_post(created_by=self.user, document_type=GRANT)

        # Create a grant
        self.grant = Grant.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            amount=Decimal("50000.00"),
            currency="USD",
            organization="National Science Foundation",
            description="Research grant for innovative AI applications in healthcare",
            status=Grant.OPEN,
        )

    def test_grant_str_representation(self):
        """Test the string representation of a grant"""
        expected = "National Science Foundation - 50000.00 USD"
        self.assertEqual(str(self.grant), expected)

    def test_is_active_open_not_expired(self):
        """Test that an open grant that's not expired is active"""
        future_date = datetime.now(UTC) + timedelta(days=30)
        self.grant.end_date = future_date
        self.grant.status = Grant.OPEN
        self.grant.save()

        self.assertTrue(self.grant.is_active())

    def test_is_active_open_expired(self):
        """Test that an open grant that's expired is not active"""
        past_date = datetime.now(UTC) - timedelta(days=1)
        self.grant.end_date = past_date
        self.grant.status = Grant.OPEN
        self.grant.save()

        self.assertFalse(self.grant.is_active())

    def test_is_active_closed(self):
        """Test that a closed grant is not active"""
        self.grant.status = Grant.CLOSED
        self.grant.save()

        self.assertFalse(self.grant.is_active())

    def test_is_active_no_end_date(self):
        """Test that an open grant with no end date is active"""
        self.grant.status = Grant.OPEN
        self.grant.end_date = None
        self.grant.save()

        self.assertTrue(self.grant.is_active())

    def test_get_llm_context_text_combines_terms_and_post_body(self):
        """LLM context text combines structured terms with the post body."""
        # Act
        text = self.grant.get_llm_context_text()

        # Assert
        self.assertIn("Organization: National Science Foundation", text)
        self.assertIn(
            "Research grant for innovative AI applications in healthcare", text
        )


class GrantLLMContextTextTests(SimpleTestCase):
    """Unit-test get_llm_context_text logic without a database."""

    def test_combines_metadata_and_post_markdown(self):
        # Arrange
        grant = MagicMock()
        grant.short_title = "My RFP"
        grant.organization = "NIH"
        grant.description = "Do good science."
        post = MagicMock()
        post.get_full_markdown.return_value = "# Details\nMore"
        post.renderable_text = "Rendered duplicate details"
        grant.unified_document.posts.first.return_value = post

        # Act
        text = Grant.get_llm_context_text(grant)

        # Assert
        self.assertIn("My RFP", text)
        self.assertIn("NIH", text)
        self.assertIn("Do good science.", text)
        self.assertIn("# Details", text)
        self.assertNotIn("Rendered duplicate details", text)

    def test_uses_rendered_post_text_when_markdown_is_unavailable(self):
        # Arrange
        grant = MagicMock()
        grant.short_title = "My RFP"
        grant.organization = "NIH"
        grant.description = "Do good science."
        post = MagicMock()
        post.get_full_markdown.return_value = None
        post.renderable_text = "Rendered call requirements"
        grant.unified_document.posts.first.return_value = post

        # Act
        text = Grant.get_llm_context_text(grant)

        # Assert
        self.assertIn("Rendered call requirements", text)

    def test_handles_missing_post(self):
        # Arrange
        grant = MagicMock()
        grant.short_title = None
        grant.organization = None
        grant.description = "Solo body"
        grant.unified_document.posts.first.return_value = None

        # Act / Assert
        self.assertEqual(Grant.get_llm_context_text(grant).strip(), "Solo body")
