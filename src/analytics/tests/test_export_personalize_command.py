"""
Integration tests for export_personalize_interactions management command.

Tests the full command execution including date filtering,
output path handling, and CSV format validation.
"""

import csv
import os
import tempfile
from datetime import timedelta
from io import StringIO

from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from analytics.services.personalize_constants import INTERACTION_CSV_HEADERS
from paper.models import Paper
from purchase.related_models.grant_application_model import GrantApplication
from purchase.related_models.grant_model import Grant
from reputation.related_models.bounty import Bounty, BountySolution
from reputation.related_models.escrow import Escrow
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User


class TestExportPersonalizeCommand(TestCase):
    """Tests for export_personalize_interactions management command"""

    def setUp(self):
        self.user = User.objects.create(username="testuser", email="test@example.com")
        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        self.paper = Paper.objects.create(
            title="Test Paper",
            unified_document=self.unified_doc,
            uploaded_by=self.user,
        )

        escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
        )

        self.bounty = Bounty.objects.create(
            created_by=self.user,
            escrow=escrow,
            unified_document=self.unified_doc,
        )

    def test_command_basic_execution(self):
        """Test command runs successfully with default parameters"""
        # Create a solution
        BountySolution.objects.create(
            bounty=self.bounty,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=self.paper.id,
            status=BountySolution.Status.SUBMITTED,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_output.csv")
            out = StringIO()

            call_command(
                "export_personalize_interactions", output_path=output_path, stdout=out
            )

            # Check file was created
            self.assertTrue(os.path.exists(output_path))

            # Check output message
            output = out.getvalue()
            self.assertIn("Successfully exported", output)
            self.assertIn("interactions to", output)

    def test_command_with_date_range(self):
        """Test command filters by date range correctly"""
        # Create solutions on different dates
        now = timezone.now()
        past_date = now - timedelta(days=10)

        # Solution within range
        solution_in_range = BountySolution.objects.create(
            bounty=self.bounty,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=self.paper.id,
            status=BountySolution.Status.SUBMITTED,
        )
        solution_in_range.created_date = now - timedelta(days=5)
        solution_in_range.save()

        # Solution outside range
        solution_out_range = BountySolution.objects.create(
            bounty=self.bounty,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=self.paper.id,
            status=BountySolution.Status.SUBMITTED,
        )
        solution_out_range.created_date = past_date
        solution_out_range.save()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_output.csv")
            start_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
            end_date = now.strftime("%Y-%m-%d")

            call_command(
                "export_personalize_interactions",
                output_path=output_path,
                start_date=start_date,
                end_date=end_date,
                stdout=StringIO(),
            )

            # Read CSV and verify only one solution was exported
            with open(output_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)

            # Should have header + 1 interaction
            self.assertEqual(len(rows), 2)

    def test_command_output_path(self):
        """Test command respects custom output path"""
        BountySolution.objects.create(
            bounty=self.bounty,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=self.paper.id,
            status=BountySolution.Status.SUBMITTED,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = os.path.join(tmpdir, "custom", "path", "output.csv")

            call_command(
                "export_personalize_interactions",
                output_path=custom_path,
                stdout=StringIO(),
            )

            # Check file was created at custom path
            self.assertTrue(os.path.exists(custom_path))

    def test_command_default_output(self):
        """Test command creates default .tmp directory"""
        BountySolution.objects.create(
            bounty=self.bounty,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=self.paper.id,
            status=BountySolution.Status.SUBMITTED,
        )

        default_path = ".tmp/personalize_interactions.csv"

        try:
            call_command("export_personalize_interactions", stdout=StringIO())

            # Check file was created
            self.assertTrue(os.path.exists(default_path))
        finally:
            # Cleanup
            if os.path.exists(default_path):
                os.remove(default_path)
            if os.path.exists(".tmp"):
                try:
                    os.rmdir(".tmp")
                except OSError:
                    pass  # Directory not empty or doesn't exist

    def test_csv_format(self):
        """Test CSV has correct headers and format"""
        # Create awarded solution (generates 1 AWARDED interaction)
        BountySolution.objects.create(
            bounty=self.bounty,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=self.paper.id,
            status=BountySolution.Status.AWARDED,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_output.csv")

            call_command(
                "export_personalize_interactions",
                output_path=output_path,
                stdout=StringIO(),
            )

            # Read and validate CSV
            with open(output_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)

            # Check headers
            self.assertEqual(rows[0], INTERACTION_CSV_HEADERS)

            # Check we have 1 data row (AWARDED only)
            self.assertEqual(len(rows), 2)  # header + 1 interaction

            # Validate data row structure
            awarded_row = rows[1]
            self.assertEqual(len(awarded_row), 8)
            # USER_ID
            self.assertEqual(awarded_row[0], str(self.user.id))
            # ITEM_ID
            self.assertEqual(awarded_row[1], str(self.unified_doc.id))
            # EVENT_TYPE
            self.assertEqual(awarded_row[2], "BOUNTY_SOLUTION_AWARDED")
            self.assertEqual(awarded_row[3], "3.0")  # EVENT_VALUE
            self.assertTrue(awarded_row[5].isdigit())  # TIMESTAMP

    def test_command_with_invalid_date_format(self):
        """Test command handles invalid date format gracefully"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_output.csv")
            out = StringIO()

            call_command(
                "export_personalize_interactions",
                output_path=output_path,
                start_date="invalid-date",
                stdout=out,
            )

            output = out.getvalue()
            self.assertIn("Invalid start date format", output)

    def test_command_statistics_output(self):
        """Test command outputs correct statistics"""
        # Create 2 solutions, one submitted and one awarded
        BountySolution.objects.create(
            bounty=self.bounty,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=self.paper.id,
            status=BountySolution.Status.SUBMITTED,
        )

        BountySolution.objects.create(
            bounty=self.bounty,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=self.paper.id,
            status=BountySolution.Status.AWARDED,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_output.csv")
            out = StringIO()

            call_command(
                "export_personalize_interactions", output_path=output_path, stdout=out
            )

            output = out.getvalue()
            self.assertIn("Total records processed: 2", output)
            self.assertIn("Interactions exported: 2", output)  # 1 + 1

    def test_command_skips_solutions_without_unified_doc(self):
        """Test command skips solutions that can't be mapped to unified doc"""
        # Create a paper without unified doc
        paper_no_doc = Paper.objects.create(
            title="Test Paper No Doc",
            unified_document=None,
            uploaded_by=self.user,
        )

        BountySolution.objects.create(
            bounty=self.bounty,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=paper_no_doc.id,
            status=BountySolution.Status.SUBMITTED,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_output.csv")
            out = StringIO()

            call_command(
                "export_personalize_interactions", output_path=output_path, stdout=out
            )

            output = out.getvalue()
            self.assertIn("Solutions skipped (no unified doc): 1", output)
            self.assertIn("Interactions exported: 0", output)

    def test_export_with_rfp_events(self):
        """Test exporting RFP (Grant) creation events."""
        # Create a grant unified document
        grant_unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=GRANT
        )

        # Create a grant post
        ResearchhubPost.objects.create(
            title="Test Grant",
            document_type=GRANT,
            unified_document=grant_unified_doc,
            created_by=self.user,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_output.csv")
            out = StringIO()

            call_command(
                "export_personalize_interactions",
                output_path=output_path,
                event_types=["rfp"],
                stdout=out,
            )

            # Read and validate CSV
            with open(output_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)

            # Check headers
            self.assertEqual(rows[0], INTERACTION_CSV_HEADERS)

            # Check we have 1 RFP_CREATED event
            self.assertEqual(len(rows), 2)  # header + 1 interaction

            # Validate RFP row
            rfp_row = rows[1]
            self.assertEqual(rfp_row[0], str(self.user.id))  # USER_ID
            self.assertEqual(rfp_row[1], str(grant_unified_doc.id))  # ITEM_ID
            self.assertEqual(rfp_row[2], "RFP_CREATED")  # EVENT_TYPE
            self.assertEqual(rfp_row[3], "3.0")  # EVENT_VALUE

            # Check output statistics
            output = out.getvalue()
            self.assertIn("Total records processed: 1", output)
            self.assertIn("Interactions exported: 1", output)
            self.assertIn("rfp:", output)

    def test_export_with_multiple_event_types(self):
        """Test exporting both bounty solutions and RFPs together."""
        # Create bounty solution
        BountySolution.objects.create(
            bounty=self.bounty,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=self.paper.id,
            status=BountySolution.Status.AWARDED,
        )

        # Create grant
        grant_unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=GRANT
        )
        ResearchhubPost.objects.create(
            title="Test Grant",
            document_type=GRANT,
            unified_document=grant_unified_doc,
            created_by=self.user,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_output.csv")
            out = StringIO()

            call_command(
                "export_personalize_interactions",
                output_path=output_path,
                event_types=["bounty_solution", "rfp"],
                stdout=out,
            )

            # Read and validate CSV
            with open(output_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)

            # Should have 2 interactions (1 AWARDED + 1 RFP_CREATED)
            self.assertEqual(len(rows), 3)  # header + 2 interactions

            # Check event types present
            event_types = [row[2] for row in rows[1:]]
            self.assertIn("BOUNTY_SOLUTION_AWARDED", event_types)
            self.assertIn("RFP_CREATED", event_types)

            # Check output statistics
            output = out.getvalue()
            self.assertIn("Total records processed: 2", output)
            self.assertIn("Interactions exported: 2", output)
            self.assertIn("bounty_solution:", output)
            self.assertIn("rfp:", output)

    def test_export_with_proposal_events(self):
        """Test exporting PROPOSAL (Preregistration) creation events."""
        # Create a preregistration unified document
        proposal_unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )

        # Create a preregistration post
        ResearchhubPost.objects.create(
            title="Test Proposal",
            document_type=PREREGISTRATION,
            unified_document=proposal_unified_doc,
            created_by=self.user,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_output.csv")
            out = StringIO()

            call_command(
                "export_personalize_interactions",
                output_path=output_path,
                event_types=["proposal"],
                stdout=out,
            )

            # Read and validate CSV
            with open(output_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)

            # Check headers
            self.assertEqual(rows[0], INTERACTION_CSV_HEADERS)

            # Check we have 1 PROPOSAL_CREATED event
            self.assertEqual(len(rows), 2)  # header + 1 interaction

            # Validate PROPOSAL row
            proposal_row = rows[1]
            self.assertEqual(proposal_row[0], str(self.user.id))  # USER_ID
            self.assertEqual(proposal_row[1], str(proposal_unified_doc.id))  # ITEM_ID
            self.assertEqual(proposal_row[2], "PROPOSAL_CREATED")  # EVENT_TYPE
            self.assertEqual(proposal_row[3], "3.0")  # EVENT_VALUE

            # Check output statistics
            output = out.getvalue()
            self.assertIn("Total records processed: 1", output)
            self.assertIn("Interactions exported: 1", output)
            self.assertIn("proposal:", output)

    def test_export_with_all_event_types(self):
        """Test exporting all event types together."""
        # Create bounty solution
        BountySolution.objects.create(
            bounty=self.bounty,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=self.paper.id,
            status=BountySolution.Status.SUBMITTED,
        )

        # Create grant
        grant_unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=GRANT
        )
        ResearchhubPost.objects.create(
            title="Test Grant",
            document_type=GRANT,
            unified_document=grant_unified_doc,
            created_by=self.user,
        )

        # Create proposal
        proposal_unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        ResearchhubPost.objects.create(
            title="Test Proposal",
            document_type=PREREGISTRATION,
            unified_document=proposal_unified_doc,
            created_by=self.user,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_output.csv")
            out = StringIO()

            # Export all event types (default behavior)
            call_command(
                "export_personalize_interactions",
                output_path=output_path,
                stdout=out,
            )

            # Read and validate CSV
            with open(output_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)

            # Should have 3 interactions (1 SUBMITTED + 1 RFP + 1 PROPOSAL)
            self.assertEqual(len(rows), 4)  # header + 3 interactions

            # Check event types present
            event_types = [row[2] for row in rows[1:]]
            self.assertIn("BOUNTY_SOLUTION_SUBMITTED", event_types)
            self.assertIn("RFP_CREATED", event_types)
            self.assertIn("PROPOSAL_CREATED", event_types)

            # Check output statistics
            output = out.getvalue()
            self.assertIn("Total records processed: 3", output)
            self.assertIn("Interactions exported: 3", output)
            self.assertIn("bounty_solution:", output)
            self.assertIn("rfp:", output)
            self.assertIn("proposal:", output)

    def test_export_with_bounty_created_events(self):
        """Test exporting BOUNTY_CREATED events."""
        # The bounty already exists from setUp
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_output.csv")
            out = StringIO()

            call_command(
                "export_personalize_interactions",
                output_path=output_path,
                event_types=["bounty"],
                stdout=out,
            )

            # Read and validate CSV
            with open(output_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)

            # Check headers
            self.assertEqual(rows[0], INTERACTION_CSV_HEADERS)

            # Check we have 1 BOUNTY_CREATED event
            self.assertEqual(len(rows), 2)  # header + 1 interaction

            # Validate BOUNTY row
            bounty_row = rows[1]
            self.assertEqual(bounty_row[0], str(self.user.id))  # USER_ID
            self.assertEqual(bounty_row[1], str(self.unified_doc.id))  # ITEM_ID
            self.assertEqual(bounty_row[2], "BOUNTY_CREATED")  # EVENT_TYPE
            self.assertEqual(bounty_row[3], "3.0")  # EVENT_VALUE

            # Check output statistics
            output = out.getvalue()
            self.assertIn("Total records processed: 1", output)
            self.assertIn("Interactions exported: 1", output)
            self.assertIn("bounty:", output)

    def test_export_with_bounty_contribution_events(self):
        """Test exporting BOUNTY_CONTRIBUTED events."""
        # Create a contributor user
        contributor = User.objects.create(
            username="contributor", email="contributor@example.com"
        )

        # Create a child bounty (contribution)
        Bounty.objects.create(
            created_by=contributor,
            escrow=self.bounty.escrow,
            unified_document=self.unified_doc,
            amount=50,
            parent=self.bounty,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_output.csv")
            out = StringIO()

            call_command(
                "export_personalize_interactions",
                output_path=output_path,
                event_types=["bounty_contribution"],
                stdout=out,
            )

            # Read and validate CSV
            with open(output_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)

            # Check headers
            self.assertEqual(rows[0], INTERACTION_CSV_HEADERS)

            # Check we have 1 BOUNTY_CONTRIBUTED event
            self.assertEqual(len(rows), 2)  # header + 1 interaction

            # Validate contribution row
            contribution_row = rows[1]
            self.assertEqual(contribution_row[0], str(contributor.id))  # USER_ID
            self.assertEqual(contribution_row[1], str(self.unified_doc.id))  # ITEM_ID
            self.assertEqual(contribution_row[2], "BOUNTY_CONTRIBUTED")  # EVENT_TYPE
            self.assertEqual(contribution_row[3], "2.0")  # EVENT_VALUE

            # Check output statistics
            output = out.getvalue()
            self.assertIn("Total records processed: 1", output)
            self.assertIn("Interactions exported: 1", output)
            self.assertIn("bounty_contribution:", output)

    def test_export_separates_main_bounties_from_contributions(self):
        """Test that main bounties and contributions are tracked separately."""
        # Create a contributor user
        contributor = User.objects.create(
            username="contributor", email="contributor@example.com"
        )

        # Main bounty already exists from setUp
        # Create a child bounty (contribution)
        Bounty.objects.create(
            created_by=contributor,
            escrow=self.bounty.escrow,
            unified_document=self.unified_doc,
            amount=50,
            parent=self.bounty,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_output.csv")
            out = StringIO()

            call_command(
                "export_personalize_interactions",
                output_path=output_path,
                event_types=["bounty", "bounty_contribution"],
                stdout=out,
            )

            # Read and validate CSV
            with open(output_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)

            # Should have 2 interactions: 1 BOUNTY_CREATED + 1 BOUNTY_CONTRIBUTED
            self.assertEqual(len(rows), 3)  # header + 2 interactions

            # Extract event types
            event_types = [row[2] for row in rows[1:]]
            self.assertIn("BOUNTY_CREATED", event_types)
            self.assertIn("BOUNTY_CONTRIBUTED", event_types)

            # Check output statistics
            output = out.getvalue()
            self.assertIn("Total records processed: 2", output)
            self.assertIn("Interactions exported: 2", output)
            self.assertIn("bounty:", output)
            self.assertIn("bounty_contribution:", output)

    def test_export_with_rfp_application_events(self):
        """Test exporting RFP_APPLIED events."""
        # Create grant unified document
        grant_unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=GRANT
        )

        # Create grant post
        ResearchhubPost.objects.create(
            created_by=self.user,
            unified_document=grant_unified_doc,
            document_type=GRANT,
            title="Test Grant",
        )

        # Create grant
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=grant_unified_doc,
            amount=10000,
            description="Test grant description",
        )

        # Create applicant
        applicant = User.objects.create(
            username="applicant", email="applicant@example.com"
        )

        # Create preregistration unified document
        prereg_unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )

        # Create preregistration post
        prereg_post = ResearchhubPost.objects.create(
            created_by=applicant,
            unified_document=prereg_unified_doc,
            document_type=PREREGISTRATION,
            title="Test Preregistration",
        )

        # Create grant application
        GrantApplication.objects.create(
            grant=grant,
            preregistration_post=prereg_post,
            applicant=applicant,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_output.csv")
            out = StringIO()

            call_command(
                "export_personalize_interactions",
                output_path=output_path,
                event_types=["rfp_application"],
                stdout=out,
            )

            # Read and validate CSV
            with open(output_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)

            # Check headers
            self.assertEqual(rows[0], INTERACTION_CSV_HEADERS)

            # Check we have 1 RFP_APPLIED event
            self.assertEqual(len(rows), 2)  # header + 1 interaction

            # Validate application row
            app_row = rows[1]
            self.assertEqual(app_row[0], str(applicant.id))  # USER_ID
            self.assertEqual(app_row[1], str(grant_unified_doc.id))  # ITEM_ID
            self.assertEqual(app_row[2], "RFP_APPLIED")  # EVENT_TYPE
            self.assertEqual(app_row[3], "3.0")  # EVENT_VALUE

            # Check output statistics
            output = out.getvalue()
            self.assertIn("Total records processed: 1", output)
            self.assertIn("Interactions exported: 1", output)
            self.assertIn("rfp_application:", output)
