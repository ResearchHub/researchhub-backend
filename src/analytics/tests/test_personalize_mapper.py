"""
Unit tests for personalize_mapper.py

Tests all mapper functions to ensure correct transformation of
bounty solution data to AWS Personalize format.
"""

from datetime import datetime, timezone
from unittest.mock import Mock, patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from analytics.services.personalize_constants import (
    BOUNTY_SOLUTION_AWARDED,
    BOUNTY_SOLUTION_SUBMITTED,
    EVENT_WEIGHTS,
)
from analytics.services.personalize_mappers.bounty_solution_mapper import (
    BountySolutionMapper,
)
from analytics.services.personalize_utils import (
    datetime_to_epoch_seconds,
    format_interaction_csv_row,
    get_unified_document_id,
)
from paper.models import Paper
from reputation.related_models.bounty import BountySolution
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User


class TestGetUnifiedDocumentId(TestCase):
    """Tests for get_unified_document_id function"""

    def setUp(self):
        self.user = User.objects.create(username="testuser", email="test@example.com")
        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )

    def test_get_unified_document_id_for_paper(self):
        """Test extracting unified document ID from a Paper"""
        paper = Paper.objects.create(
            title="Test Paper",
            unified_document=self.unified_doc,
            uploaded_by=self.user,
        )
        content_type = ContentType.objects.get_for_model(Paper)

        result = get_unified_document_id(content_type, paper.id)

        self.assertEqual(result, self.unified_doc.id)

    def test_get_unified_document_id_for_post(self):
        """Test extracting unified document ID from a ResearchhubPost"""
        post = ResearchhubPost.objects.create(
            title="Test Post",
            unified_document=self.unified_doc,
            created_by=self.user,
        )
        content_type = ContentType.objects.get_for_model(ResearchhubPost)

        result = get_unified_document_id(content_type, post.id)

        self.assertEqual(result, self.unified_doc.id)

    def test_get_unified_document_id_for_comment(self):
        """Test extracting unified document ID from a RhCommentModel"""
        # Create a comment with a thread that has a unified document
        mock_thread = Mock()
        mock_thread.unified_document = self.unified_doc

        with patch.object(
            RhCommentModel.objects, "get", return_value=Mock(thread=mock_thread)
        ):
            content_type = ContentType.objects.get_for_model(RhCommentModel)
            result = get_unified_document_id(content_type, 1)

            self.assertEqual(result, self.unified_doc.id)

    def test_get_unified_document_id_for_nonexistent_object(self):
        """Test that None is returned for non-existent object"""
        content_type = ContentType.objects.get_for_model(Paper)

        result = get_unified_document_id(content_type, 99999)

        self.assertIsNone(result)


class TestDatetimeToEpochSeconds(TestCase):
    """Tests for datetime_to_epoch_seconds function"""

    def test_timestamp_conversion(self):
        """Test datetime to Unix epoch conversion"""
        dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        expected_timestamp = 1704110400  # Unix timestamp for 2024-01-01 12:00:00 UTC

        result = datetime_to_epoch_seconds(dt)

        self.assertEqual(result, expected_timestamp)

    def test_timestamp_conversion_with_milliseconds(self):
        """Test that milliseconds are handled (truncated to seconds)"""
        dt = datetime(2024, 1, 1, 12, 0, 0, 500000, tzinfo=timezone.utc)

        result = datetime_to_epoch_seconds(dt)

        # Should be an integer (seconds only)
        self.assertIsInstance(result, int)


class TestMapBountySolutionToInteractions(TestCase):
    """Tests for map_bounty_solution_to_interactions function"""

    def setUp(self):
        from reputation.related_models.bounty import Bounty
        from reputation.related_models.escrow import Escrow

        self.user = User.objects.create(username="testuser", email="test@example.com")
        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        self.paper = Paper.objects.create(
            title="Test Paper",
            unified_document=self.unified_doc,
            uploaded_by=self.user,
        )

        # Create escrow first with temporary object_id
        bounty_ct = ContentType.objects.get_for_model(Bounty)
        escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
            content_type=bounty_ct,
            object_id=1,  # Temporary, will be updated
        )

        # Create bounty with escrow and item reference
        paper_ct = ContentType.objects.get_for_model(Paper)
        self.bounty = Bounty.objects.create(
            created_by=self.user,
            unified_document=self.unified_doc,
            escrow=escrow,
            item_content_type=paper_ct,
            item_object_id=self.paper.id,
        )

        # Update escrow's object_id to point to bounty
        escrow.object_id = self.bounty.id
        escrow.save()

    def test_map_submitted_bounty_solution(self):
        """Test mapping a SUBMITTED bounty solution creates one interaction"""
        solution = BountySolution.objects.create(
            bounty=self.bounty,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=self.paper.id,
            status=BountySolution.Status.SUBMITTED,
        )

        mapper = BountySolutionMapper()
        interactions = mapper.map_to_interactions(solution)

        self.assertEqual(len(interactions), 1)
        self.assertEqual(interactions[0]["EVENT_TYPE"], BOUNTY_SOLUTION_SUBMITTED)
        self.assertEqual(
            interactions[0]["EVENT_VALUE"], EVENT_WEIGHTS[BOUNTY_SOLUTION_SUBMITTED]
        )
        self.assertEqual(interactions[0]["USER_ID"], str(self.user.id))
        self.assertEqual(interactions[0]["ITEM_ID"], str(self.unified_doc.id))
        self.assertIsNone(interactions[0]["DEVICE"])
        self.assertIsNone(interactions[0]["IMPRESSION"])
        self.assertIsNone(interactions[0]["RECOMMENDATION_ID"])

    def test_map_awarded_bounty_solution(self):
        """Test mapping an AWARDED bounty solution creates one AWARDED interaction"""
        solution = BountySolution.objects.create(
            bounty=self.bounty,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=self.paper.id,
            status=BountySolution.Status.AWARDED,
            awarded_amount=100,
        )

        mapper = BountySolutionMapper()
        interactions = mapper.map_to_interactions(solution)

        self.assertEqual(len(interactions), 1)

        # Interaction should be AWARDED
        self.assertEqual(interactions[0]["EVENT_TYPE"], BOUNTY_SOLUTION_AWARDED)
        self.assertEqual(
            interactions[0]["EVENT_VALUE"], EVENT_WEIGHTS[BOUNTY_SOLUTION_AWARDED]
        )
        self.assertEqual(
            interactions[0]["TIMESTAMP"],
            datetime_to_epoch_seconds(solution.updated_date),
        )
        self.assertEqual(interactions[0]["USER_ID"], str(self.user.id))
        self.assertEqual(interactions[0]["ITEM_ID"], str(self.unified_doc.id))

    def test_map_rejected_bounty_solution(self):
        """Test mapping a REJECTED bounty solution creates no interactions"""
        solution = BountySolution.objects.create(
            bounty=self.bounty,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=self.paper.id,
            status=BountySolution.Status.REJECTED,
        )

        mapper = BountySolutionMapper()
        interactions = mapper.map_to_interactions(solution)

        # REJECTED solutions should not create interactions
        self.assertEqual(len(interactions), 0)


class TestFormatInteractionCsvRow(TestCase):
    """Tests for format_interaction_csv_row function"""

    def test_format_interaction_csv_row(self):
        """Test formatting interaction dict to CSV row"""
        interaction = {
            "USER_ID": "123",
            "ITEM_ID": "456",
            "EVENT_TYPE": BOUNTY_SOLUTION_SUBMITTED,
            "EVENT_VALUE": 2.0,
            "DEVICE": None,
            "TIMESTAMP": 1704110400,
            "IMPRESSION": None,
            "RECOMMENDATION_ID": None,
        }

        row = format_interaction_csv_row(interaction)

        self.assertEqual(len(row), 8)
        self.assertEqual(row[0], "123")  # USER_ID
        self.assertEqual(row[1], "456")  # ITEM_ID
        self.assertEqual(row[2], BOUNTY_SOLUTION_SUBMITTED)  # EVENT_TYPE
        self.assertEqual(row[3], 2.0)  # EVENT_VALUE
        self.assertEqual(row[4], "")  # DEVICE (None -> "")
        self.assertEqual(row[5], 1704110400)  # TIMESTAMP
        self.assertEqual(row[6], "")  # IMPRESSION (None -> "")
        self.assertEqual(row[7], "")  # RECOMMENDATION_ID (None -> "")

    def test_format_interaction_csv_row_with_values(self):
        """Test formatting when optional fields have values"""
        interaction = {
            "USER_ID": "123",
            "ITEM_ID": "456",
            "EVENT_TYPE": BOUNTY_SOLUTION_AWARDED,
            "EVENT_VALUE": 3.0,
            "DEVICE": "mobile",
            "TIMESTAMP": 1704110400,
            "IMPRESSION": "789,101,112",
            "RECOMMENDATION_ID": "rec_123",
        }

        row = format_interaction_csv_row(interaction)

        self.assertEqual(row[4], "mobile")  # DEVICE
        self.assertEqual(row[6], "789,101,112")  # IMPRESSION
        self.assertEqual(row[7], "rec_123")  # RECOMMENDATION_ID
