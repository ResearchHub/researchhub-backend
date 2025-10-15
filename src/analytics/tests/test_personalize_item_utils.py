"""
Unit tests for personalize_item_utils.

Tests text cleaning, hub mapping, and metrics extraction functions.
"""

from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from analytics.services.personalize_item_utils import (
    clean_text_for_csv,
    get_author_ids,
    get_bounty_metrics,
    get_hub_mapping,
    get_last_comment_timestamp,
    get_proposal_metrics,
    get_rfp_metrics,
)
from hub.models import Hub
from paper.models import Paper
from purchase.models import Fundraise, GrantApplication
from reputation.models import Bounty, BountySolution, Escrow
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from user.models import User


class CleanTextForCSVTest(TestCase):
    """Test text cleaning for CSV safety."""

    def test_clean_text_strips_html(self):
        """Test that HTML tags are stripped."""
        text = "<p>Hello <strong>world</strong>!</p>"
        result = clean_text_for_csv(text)
        self.assertEqual(result, "Hello world!")

    def test_clean_text_removes_newlines(self):
        """Test that newlines are replaced with spaces."""
        text = "Line 1\nLine 2\rLine 3"
        result = clean_text_for_csv(text)
        self.assertEqual(result, "Line 1 Line 2 Line 3")

    def test_clean_text_removes_tabs(self):
        """Test that tabs are replaced with spaces."""
        text = "Column1\tColumn2\tColumn3"
        result = clean_text_for_csv(text)
        self.assertEqual(result, "Column1 Column2 Column3")

    def test_clean_text_collapses_spaces(self):
        """Test that multiple spaces are collapsed."""
        text = "Too   many    spaces"
        result = clean_text_for_csv(text)
        self.assertEqual(result, "Too many spaces")

    def test_clean_text_truncates_long_text(self):
        """Test that very long text is truncated."""
        text = "A" * 20000
        result = clean_text_for_csv(text)
        self.assertEqual(len(result), 10000)

    def test_clean_text_handles_none(self):
        """Test that None input returns None."""
        result = clean_text_for_csv(None)
        self.assertIsNone(result)

    def test_clean_text_handles_empty_string(self):
        """Test that empty string returns None."""
        result = clean_text_for_csv("")
        self.assertIsNone(result)


class GetHubMappingTest(TestCase):
    """Test hub mapping extraction."""

    def setUp(self):
        """Set up test fixtures."""
        self.hub1 = Hub.objects.create(name="Computer Science", slug="computer-science")
        self.hub2 = Hub.objects.create(name="Machine Learning", slug="machine-learning")

        self.user = User.objects.create(email="test@example.com", username="testuser")

    def test_get_hub_mapping_with_primary_hub(self):
        """Test hub mapping uses primary hub as fallback."""
        # Create a unified document with a primary hub
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        unified_doc.hubs.add(self.hub1)

        paper = Paper.objects.create(
            title="Test Paper", uploaded_by=self.user, unified_document=unified_doc
        )

        hub_l1, hub_l2 = get_hub_mapping(unified_doc, paper)

        # Should return the hub slug, L2 should be None
        self.assertEqual(hub_l1, "computer-science")
        self.assertIsNone(hub_l2)

    def test_get_hub_mapping_no_hubs(self):
        """Test hub mapping when no hubs are assigned."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")

        paper = Paper.objects.create(
            title="Test Paper", uploaded_by=self.user, unified_document=unified_doc
        )

        hub_l1, hub_l2 = get_hub_mapping(unified_doc, paper)

        self.assertIsNone(hub_l1)
        self.assertIsNone(hub_l2)


class GetAuthorIDsTest(TestCase):
    """Test author ID extraction."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create(email="test@example.com", username="testuser")

    def test_get_author_ids_for_post(self):
        """Test getting author ID for a post."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION"
        )

        post = ResearchhubPost.objects.create(
            title="Test Post", created_by=self.user, unified_document=unified_doc
        )

        result = get_author_ids(unified_doc, post)

        # Should return the author profile ID
        self.assertIsNotNone(result)
        self.assertEqual(result, str(self.user.author_profile.id))

    def test_get_author_ids_no_author(self):
        """Test getting author IDs when there are none."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION"
        )

        post = ResearchhubPost.objects.create(
            title="Test Post", created_by=None, unified_document=unified_doc
        )

        result = get_author_ids(unified_doc, post)
        self.assertIsNone(result)


class GetBountyMetricsTest(TestCase):
    """Test bounty metrics extraction."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create(email="test@example.com", username="testuser")

        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="QUESTION"
        )

        self.paper = Paper.objects.create(
            title="Test Paper", uploaded_by=self.user, unified_document=self.unified_doc
        )

    def test_get_bounty_metrics_with_open_bounty(self):
        """Test getting bounty metrics with an open bounty."""
        # Create escrow
        escrow = Escrow.objects.create(
            created_by=self.user, hold_type=Escrow.BOUNTY, amount_holding=100
        )

        # Create bounty
        content_type = ContentType.objects.get_for_model(Paper)
        expiration_date = timezone.now() + timedelta(days=30)

        bounty = Bounty.objects.create(
            created_by=self.user,
            escrow=escrow,
            amount=100,
            status=Bounty.OPEN,
            expiration_date=expiration_date,
            item_content_type=content_type,
            item_object_id=self.paper.id,
            unified_document=self.unified_doc,
        )

        # Create a solution
        BountySolution.objects.create(bounty=bounty, status=BountySolution.SUBMITTED)

        metrics = get_bounty_metrics(self.unified_doc)

        self.assertEqual(metrics["BOUNTY_AMOUNT"], 100.0)
        self.assertIsNotNone(metrics["BOUNTY_EXPIRES_AT"])
        self.assertEqual(metrics["BOUNTY_NUM_OF_SOLUTIONS"], 1)

    def test_get_bounty_metrics_no_bounty(self):
        """Test getting bounty metrics when there are no bounties."""
        metrics = get_bounty_metrics(self.unified_doc)

        self.assertIsNone(metrics["BOUNTY_AMOUNT"])
        self.assertIsNone(metrics["BOUNTY_EXPIRES_AT"])
        self.assertIsNone(metrics["BOUNTY_NUM_OF_SOLUTIONS"])


class GetProposalMetricsTest(TestCase):
    """Test proposal (fundraise) metrics extraction."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create(email="test@example.com", username="testuser")

        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PREREGISTRATION"
        )

    def test_get_proposal_metrics_with_fundraise(self):
        """Test getting proposal metrics with an open fundraise."""
        # Create escrow for fundraise
        fundraise_ct = ContentType.objects.get_for_model(Fundraise)
        escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.FUNDRAISE,
            amount_holding=500,
            content_type=fundraise_ct,
        )

        # Create fundraise
        end_date = timezone.now() + timedelta(days=30)
        fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=self.unified_doc,
            escrow=escrow,
            status=Fundraise.OPEN,
            goal_amount=1000,
            end_date=end_date,
        )

        # Link escrow to fundraise
        escrow.object_id = fundraise.id
        escrow.save()

        metrics = get_proposal_metrics(self.unified_doc)

        self.assertIsNotNone(metrics["PROPOSAL_AMOUNT"])
        self.assertIsNotNone(metrics["PROPOSAL_EXPIRES_AT"])
        self.assertEqual(metrics["PROPOSAL_NUM_OF_FUNDERS"], 0)

    def test_get_proposal_metrics_no_fundraise(self):
        """Test getting proposal metrics when there are no fundraises."""
        metrics = get_proposal_metrics(self.unified_doc)

        self.assertIsNone(metrics["PROPOSAL_AMOUNT"])
        self.assertIsNone(metrics["PROPOSAL_EXPIRES_AT"])
        self.assertIsNone(metrics["PROPOSAL_NUM_OF_FUNDERS"])


class GetRFPMetricsTest(TestCase):
    """Test RFP metrics extraction."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create(email="test@example.com", username="testuser")

        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="GRANT"
        )

        self.post = ResearchhubPost.objects.create(
            title="Test Grant",
            document_type="GRANT",
            created_by=self.user,
            unified_document=self.unified_doc,
        )

    def test_get_rfp_metrics_with_applications(self):
        """Test getting RFP metrics with grant applications."""
        # Create grant application
        GrantApplication.objects.create(
            user=self.user, unified_document=self.unified_doc
        )

        metrics = get_rfp_metrics(self.unified_doc)

        self.assertEqual(metrics["REQUEST_FOR_PROPOSAL_NUM_OF_APPLICANTS"], 1)

    def test_get_rfp_metrics_no_applications(self):
        """Test getting RFP metrics when there are no applications."""
        metrics = get_rfp_metrics(self.unified_doc)

        self.assertIsNone(metrics["REQUEST_FOR_PROPOSAL_AMOUNT"])
        self.assertIsNone(metrics["REQUEST_FOR_PROPOSAL_EXPIRES_AT"])
        self.assertEqual(metrics["REQUEST_FOR_PROPOSAL_NUM_OF_APPLICANTS"], 0)


class GetLastCommentTimestampTest(TestCase):
    """Test last comment timestamp extraction."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create(email="test@example.com", username="testuser")

        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )

        self.paper = Paper.objects.create(
            title="Test Paper", uploaded_by=self.user, unified_document=self.unified_doc
        )

    def test_get_last_comment_timestamp_with_comments(self):
        """Test getting last comment timestamp when comments exist."""
        # Create a thread
        content_type = ContentType.objects.get_for_model(Paper)
        thread = RhCommentThreadModel.objects.create(
            content_type=content_type, object_id=self.paper.id
        )

        # Create comments
        RhCommentModel.objects.create(
            thread=thread, created_by=self.user, updated_by=self.user
        )

        # Create a newer comment
        RhCommentModel.objects.create(
            thread=thread, created_by=self.user, updated_by=self.user
        )

        timestamp = get_last_comment_timestamp(self.unified_doc)

        self.assertIsNotNone(timestamp)
        self.assertIsInstance(timestamp, int)

    def test_get_last_comment_timestamp_no_comments(self):
        """Test getting last comment timestamp when there are no comments."""
        timestamp = get_last_comment_timestamp(self.unified_doc)
        self.assertIsNone(timestamp)
