"""
Integration tests for export_personalize_items management command.

Tests full export process with various document types.
"""

import csv
import os
from datetime import timedelta
from io import StringIO

from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from hub.models import Hub
from paper.models import Paper
from purchase.models import Fundraise, Grant, GrantApplication
from reputation.models import Bounty, BountySolution, Escrow
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from user.models import User


class ExportPersonalizeItemsCommandTest(TestCase):
    """Test export_personalize_items management command."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create(email="test@example.com", username="testuser")

        self.hub = Hub.objects.create(name="Computer Science", slug="computer-science")

        self.output_path = "/tmp/test_personalize_items.csv"

    def tearDown(self):
        """Clean up test files."""
        if os.path.exists(self.output_path):
            os.remove(self.output_path)

    def test_command_exports_papers(self):
        """Test that papers are exported correctly."""
        # Create paper
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", score=10
        )
        unified_doc.hubs.add(self.hub)

        Paper.objects.create(
            title="Test Paper",
            paper_title="Official Test Paper",
            abstract="This is a test abstract.",
            uploaded_by=self.user,
            unified_document=unified_doc,
            citations=5,
        )

        # Run command
        out = StringIO()
        call_command(
            "export_personalize_items", "--output", self.output_path, stdout=out
        )

        # Check output
        output = out.getvalue()
        self.assertIn("Total items exported: 1", output)
        self.assertIn("Papers: 1", output)

        # Check CSV file
        self.assertTrue(os.path.exists(self.output_path))

        with open(self.output_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

            self.assertEqual(len(rows), 1)
            row = rows[0]

            self.assertEqual(row["ITEM_ID"], str(unified_doc.id))
            self.assertEqual(row["ITEM_TYPE"], "PAPER")
            self.assertEqual(row["SCORE"], "10")
            self.assertNotEqual(row["TEXT"], "")
            self.assertNotEqual(row["TITLE"], "")

    def test_command_exports_posts(self):
        """Test that posts are exported correctly."""
        # Create post
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION", score=15
        )
        unified_doc.hubs.add(self.hub)

        ResearchhubPost.objects.create(
            title="Test Post",
            renderable_text="This is a test post.",
            created_by=self.user,
            unified_document=unified_doc,
            document_type="DISCUSSION",
        )

        # Run command
        out = StringIO()
        call_command(
            "export_personalize_items", "--output", self.output_path, stdout=out
        )

        # Check output
        output = out.getvalue()
        self.assertIn("Total items exported: 1", output)
        self.assertIn("Posts: 1", output)

        # Check CSV file
        with open(self.output_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

            self.assertEqual(len(rows), 1)
            row = rows[0]

            self.assertEqual(row["ITEM_TYPE"], "DISCUSSION")

    def test_command_excludes_note_documents(self):
        """Test that NOTE documents are excluded."""
        # Create NOTE document
        ResearchhubUnifiedDocument.objects.create(
            document_type="NOTE", is_removed=False
        )

        # Create PAPER document
        unified_doc_paper = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", is_removed=False
        )
        Paper.objects.create(
            title="Test Paper",
            uploaded_by=self.user,
            unified_document=unified_doc_paper,
        )

        # Run command
        out = StringIO()
        call_command(
            "export_personalize_items", "--output", self.output_path, stdout=out
        )

        # Should only export PAPER, not NOTE
        output = out.getvalue()
        self.assertIn("Total items exported: 1", output)

    def test_command_with_date_filters(self):
        """Test command with date range filters."""
        # Create old document
        old_date = timezone.now() - timedelta(days=100)
        old_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", is_removed=False
        )
        old_doc.created_date = old_date
        old_doc.save()

        Paper.objects.create(
            title="Old Paper", uploaded_by=self.user, unified_document=old_doc
        )

        # Create recent document
        recent_date = timezone.now() - timedelta(days=1)
        recent_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", is_removed=False
        )
        recent_doc.created_date = recent_date
        recent_doc.save()

        Paper.objects.create(
            title="Recent Paper", uploaded_by=self.user, unified_document=recent_doc
        )

        # Run command with start date filter
        start_date = (timezone.now() - timedelta(days=50)).strftime("%Y-%m-%d")
        out = StringIO()
        call_command(
            "export_personalize_items",
            "--start-date",
            start_date,
            "--output",
            self.output_path,
            stdout=out,
        )

        # Should only export recent document
        output = out.getvalue()
        self.assertIn("Total items exported: 1", output)

    def test_command_exports_bounty_metrics(self):
        """Test that bounty metrics are exported."""
        # Create unified doc with bounty
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"  # Changed from QUESTION to match the Paper object
        )

        paper = Paper.objects.create(
            title="Test Paper with Bounty",
            uploaded_by=self.user,
            unified_document=unified_doc,
        )

        # Create bounty with escrow
        content_type = ContentType.objects.get_for_model(Paper)
        bounty_ct = ContentType.objects.get_for_model(Bounty)
        expiration_date = timezone.now() + timedelta(days=30)

        # Create escrow first with temporary object_id
        escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
            amount_holding=100,
            content_type=bounty_ct,
            object_id=1,  # Temporary, will be updated
        )

        # Create bounty with escrow
        bounty = Bounty.objects.create(
            created_by=self.user,
            amount=100,
            status=Bounty.OPEN,
            expiration_date=expiration_date,
            item_content_type=content_type,
            item_object_id=paper.id,
            unified_document=unified_doc,
            escrow=escrow,
        )

        # Update escrow's object_id to point to bounty
        escrow.object_id = bounty.id
        escrow.save()

        # Create solution
        BountySolution.objects.create(
            bounty=bounty,
            created_by=self.user,
            status=BountySolution.Status.SUBMITTED,
            content_type=content_type,
            object_id=paper.id,
        )

        # Run command
        call_command("export_personalize_items", "--output", self.output_path)

        # Check CSV for bounty metrics
        with open(self.output_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

            self.assertEqual(len(rows), 1)
            row = rows[0]

            self.assertEqual(row["BOUNTY_AMOUNT"], "100.0")
            self.assertNotEqual(row["BOUNTY_EXPIRES_AT"], "")
            self.assertEqual(row["BOUNTY_NUM_OF_SOLUTIONS"], "1")

    def test_command_exports_proposal_metrics(self):
        """Test that proposal metrics are exported."""
        # Create PREREGISTRATION document
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PREREGISTRATION"
        )

        ResearchhubPost.objects.create(
            title="Test Proposal",
            document_type="PREREGISTRATION",
            created_by=self.user,
            unified_document=unified_doc,
        )

        # Create fundraise first
        end_date = timezone.now() + timedelta(days=30)
        fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=unified_doc,
            status=Fundraise.OPEN,
            goal_amount=1000,
            end_date=end_date,
        )

        # Create escrow linked to fundraise
        fundraise_ct = ContentType.objects.get_for_model(Fundraise)
        escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.FUNDRAISE,
            amount_holding=500,
            content_type=fundraise_ct,
            object_id=fundraise.id,
        )

        # Link escrow back to fundraise
        fundraise.escrow = escrow
        fundraise.save()

        # Run command
        call_command("export_personalize_items", "--output", self.output_path)

        # Check CSV for proposal metrics
        with open(self.output_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

            self.assertEqual(len(rows), 1)
            row = rows[0]

            self.assertEqual(row["PROPOSAL_AMOUNT"], "1000.0")
            self.assertNotEqual(row["PROPOSAL_EXPIRES_AT"], "")

    def test_command_exports_rfp_metrics(self):
        """Test that RFP metrics are exported."""
        # Create GRANT document
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="GRANT")

        post = ResearchhubPost.objects.create(
            title="Test Grant",
            document_type="GRANT",
            created_by=self.user,
            unified_document=unified_doc,
        )

        # Create grant
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=unified_doc,
            amount=5000.00,
            currency="USD",
            description="Test grant for RFP",
            status=Grant.OPEN,
            end_date=timezone.now() + timedelta(days=60),
        )

        # Create grant application
        GrantApplication.objects.create(
            grant=grant, applicant=self.user, preregistration_post=post
        )

        # Run command
        call_command("export_personalize_items", "--output", self.output_path)

        # Check CSV for RFP metrics
        with open(self.output_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

            self.assertEqual(len(rows), 1)
            row = rows[0]

            self.assertEqual(row["REQUEST_FOR_PROPOSAL_AMOUNT"], "5000.0")
            self.assertNotEqual(row["REQUEST_FOR_PROPOSAL_EXPIRES_AT"], "")
            self.assertEqual(row["REQUEST_FOR_PROPOSAL_NUM_OF_APPLICANTS"], "1")

    def test_command_exports_last_comment_timestamp(self):
        """Test that LAST_COMMENT_AT is exported."""
        # Create paper with comment
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")

        paper = Paper.objects.create(
            title="Test Paper", uploaded_by=self.user, unified_document=unified_doc
        )

        # Create thread and comment
        content_type = ContentType.objects.get_for_model(Paper)
        thread = RhCommentThreadModel.objects.create(
            content_type=content_type,
            object_id=paper.id,
            created_by=self.user,
        )

        RhCommentModel.objects.create(
            thread=thread, created_by=self.user, updated_by=self.user
        )

        # Run command
        call_command("export_personalize_items", "--output", self.output_path)

        # Check CSV for last comment timestamp
        with open(self.output_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

            self.assertEqual(len(rows), 1)
            row = rows[0]

            self.assertNotEqual(row["LAST_COMMENT_AT"], "")
            self.assertIsNotNone(row["LAST_COMMENT_AT"])

    def test_command_csv_format(self):
        """Test that CSV has correct headers and format."""
        # Create a simple document
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")

        Paper.objects.create(
            title="Test Paper", uploaded_by=self.user, unified_document=unified_doc
        )

        # Run command
        call_command("export_personalize_items", "--output", self.output_path)

        # Check CSV headers
        with open(self.output_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames

            # Check that all expected headers are present
            expected_headers = [
                "ITEM_ID",
                "ITEM_TYPE",
                "HUB_L1",
                "HUB_L2",
                "HUB_IDS",
                "AUTHOR_IDS",
                "CREATION_TIMESTAMP",
                "TEXT",
                "TITLE",
                "SCORE",
                "BLUESKY_COUNT_TOTAL",
                "TWEET_COUNT_TOTAL",
                "CITATION_COUNT_TOTAL",
                "BOUNTY_AMOUNT",
                "BOUNTY_EXPIRES_AT",
                "BOUNTY_NUM_OF_SOLUTIONS",
                "PROPOSAL_AMOUNT",
                "PROPOSAL_EXPIRES_AT",
                "PROPOSAL_NUM_OF_FUNDERS",
                "REQUEST_FOR_PROPOSAL_AMOUNT",
                "REQUEST_FOR_PROPOSAL_EXPIRES_AT",
                "REQUEST_FOR_PROPOSAL_NUM_OF_APPLICANTS",
                "LAST_COMMENT_AT",
            ]

            for header in expected_headers:
                self.assertIn(header, headers)

    def test_command_exports_grant_with_contacts(self):
        """Test that grants are exported with contact author IDs."""
        # Create contact users
        contact_user1 = User.objects.create(
            email="contact1@example.com", username="contact1"
        )
        contact_user2 = User.objects.create(
            email="contact2@example.com", username="contact2"
        )

        # Create grant
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="GRANT", score=5
        )
        unified_doc.hubs.add(self.hub)

        # Create the post for the grant
        ResearchhubPost.objects.create(
            title="Test Grant",
            document_type="GRANT",
            created_by=self.user,
            unified_document=unified_doc,
        )

        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=unified_doc,
            amount=50000.00,
            currency="USD",
            organization="Test Foundation",
            description="Test grant with contacts",
            status=Grant.OPEN,
        )

        # Add contacts
        grant.contacts.add(contact_user1, contact_user2)

        # Run command
        out = StringIO()
        call_command(
            "export_personalize_items", "--output", self.output_path, stdout=out
        )

        # Check CSV file
        with open(self.output_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

            self.assertEqual(len(rows), 1)
            row = rows[0]

            # Should include contact author IDs
            author_ids = row["AUTHOR_IDS"]
            self.assertIsNotNone(author_ids)
            self.assertNotEqual(author_ids, "")

            # Verify contact users' author profiles are present
            self.assertIn(str(contact_user1.author_profile.id), author_ids)
            self.assertIn(str(contact_user2.author_profile.id), author_ids)

            # Verify creator is NOT included (only contacts)
            self.assertNotIn(str(self.user.author_profile.id), author_ids)

    def test_command_with_since_parameter(self):
        """Test --since includes papers since date plus filtered older papers."""
        from datetime import datetime

        recent_date = datetime(2024, 1, 1)
        old_date = datetime(2023, 1, 1)

        # Create old external paper (should be excluded)
        old_external_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        old_paper = Paper.objects.create(
            title="Old External Paper",
            uploaded_by=self.user,
            unified_document=old_external_doc,
            retrieved_from_external_source=True,
        )
        Paper.objects.filter(id=old_paper.id).update(created_date=old_date)

        # Create recent external paper (should be included)
        recent_external_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        recent_external_doc.hubs.add(self.hub)
        recent_paper = Paper.objects.create(
            title="Recent External Paper",
            uploaded_by=self.user,
            unified_document=recent_external_doc,
            retrieved_from_external_source=True,
        )
        Paper.objects.filter(id=recent_paper.id).update(created_date=recent_date)

        # Create old native paper (should be included - always include native)
        old_native_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        old_native_doc.hubs.add(self.hub)
        old_native_paper = Paper.objects.create(
            title="Old Native Paper",
            uploaded_by=self.user,
            unified_document=old_native_doc,
            retrieved_from_external_source=False,
        )
        Paper.objects.filter(id=old_native_paper.id).update(created_date=old_date)

        # Create a post (should be included)
        post_doc = ResearchhubUnifiedDocument.objects.create(document_type="DISCUSSION")
        post_doc.hubs.add(self.hub)
        ResearchhubPost.objects.create(
            title="Test Post",
            document_type="DISCUSSION",
            created_by=self.user,
            unified_document=post_doc,
        )

        # Run command with --since parameter
        out = StringIO()
        call_command(
            "export_personalize_items",
            "--output",
            self.output_path,
            "--since",
            "2024-01-01",
            stdout=out,
        )

        # Check CSV file
        with open(self.output_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

            # Should have 3 items: recent external, old native, post
            self.assertEqual(len(rows), 3)

            item_ids = [row["ITEM_ID"] for row in rows]
            # Recent external paper should be included
            self.assertIn(str(recent_external_doc.id), item_ids)
            # Old native paper should be included
            self.assertIn(str(old_native_doc.id), item_ids)
            # Post should be included
            self.assertIn(str(post_doc.id), item_ids)
            # Old external paper should NOT be included
            self.assertNotIn(str(old_external_doc.id), item_ids)

        # Verify output message
        output = out.getvalue()
        self.assertIn("Since date: 2024-01-01", output)
        self.assertIn(
            "all papers created on or after this date will be included", output
        )
