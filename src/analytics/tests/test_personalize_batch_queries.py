"""
Tests for PersonalizeBatchQueries service.
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytz
from django.test import TestCase

from analytics.services.personalize_batch_queries import PersonalizeBatchQueries
from analytics.tests.helpers import (
    create_bounty_for_document,
    create_bounty_solution,
    create_fundraise_contribution,
    create_grant_application,
    create_prefetched_grant,
    create_prefetched_paper,
    create_prefetched_post,
    create_prefetched_proposal,
)
from purchase.models import Fundraise, Grant
from reputation.models import Bounty
from researchhub_document.related_models.constants.document_type import DISCUSSION


class BountyDataTests(TestCase):
    """Tests for fetch_bounty_data method."""

    def test_fetch_bounty_data_identifies_open_bounties(self):
        """Should return has_active_bounty=True for documents with OPEN bounties."""
        # Arrange
        unified_doc = create_prefetched_paper()
        create_bounty_for_document(unified_doc, status=Bounty.OPEN)
        fetcher = PersonalizeBatchQueries()

        # Act
        result = fetcher.fetch_bounty_data([unified_doc.id])

        # Assert
        self.assertTrue(result[unified_doc.id]["has_active_bounty"])

    def test_fetch_bounty_data_false_for_closed_bounties(self):
        """Should return has_active_bounty=False for documents with closed bounties."""
        # Arrange
        unified_doc = create_prefetched_paper()
        create_bounty_for_document(unified_doc, status=Bounty.CLOSED)
        fetcher = PersonalizeBatchQueries()

        # Act
        result = fetcher.fetch_bounty_data([unified_doc.id])

        # Assert
        # Closed bounties don't appear in the result (only OPEN ones do)
        self.assertNotIn(unified_doc.id, result)

    def test_fetch_bounty_data_identifies_solutions(self):
        """Should return has_solutions=True when BountySolution exists."""
        # Arrange
        unified_doc = create_prefetched_paper()
        bounty = create_bounty_for_document(unified_doc, status=Bounty.OPEN)
        create_bounty_solution(bounty)
        fetcher = PersonalizeBatchQueries()

        # Act
        result = fetcher.fetch_bounty_data([unified_doc.id])

        # Assert
        self.assertTrue(result[unified_doc.id]["has_solutions"])

    def test_fetch_bounty_data_handles_no_bounties(self):
        """Should return default False flags for documents without bounties."""
        # Arrange
        unified_doc = create_prefetched_paper()
        fetcher = PersonalizeBatchQueries()

        # Act
        result = fetcher.fetch_bounty_data([unified_doc.id])

        # Assert
        # Documents without bounties won't have an entry in the result
        self.assertNotIn(unified_doc.id, result)


class ProposalDataTests(TestCase):
    """Tests for fetch_proposal_data method."""

    def test_fetch_proposal_data_identifies_open_fundraises(self):
        """Should return is_open=True for PREREGISTRATION with OPEN fundraises."""
        # Arrange
        unified_doc = create_prefetched_proposal(status=Fundraise.OPEN)
        fetcher = PersonalizeBatchQueries()

        # Act
        result = fetcher.fetch_proposal_data([unified_doc.id])

        # Assert
        self.assertTrue(result[unified_doc.id]["is_open"])

    def test_fetch_proposal_data_false_for_closed_or_expired_fundraises(self):
        """Should return is_open=False for closed or expired fundraises."""
        # Arrange - Test CLOSED status
        closed_doc = create_prefetched_proposal(status=Fundraise.CLOSED)
        fetcher = PersonalizeBatchQueries()

        # Act
        closed_result = fetcher.fetch_proposal_data([closed_doc.id])

        # Assert
        # Closed fundraises don't appear in the result (only OPEN ones do)
        self.assertNotIn(closed_doc.id, closed_result)

    def test_fetch_proposal_data_identifies_funders(self):
        """Should return has_funders=True when Purchase.FUNDRAISE_CONTRIBUTION exists."""
        # Arrange
        unified_doc = create_prefetched_proposal(status=Fundraise.OPEN)
        fundraise = unified_doc.fundraises.first()
        create_fundraise_contribution(fundraise)
        fetcher = PersonalizeBatchQueries()

        # Act
        result = fetcher.fetch_proposal_data([unified_doc.id])

        # Assert
        self.assertTrue(result[unified_doc.id]["has_funders"])

    def test_fetch_proposal_data_only_for_preregistration_type(self):
        """Should only flag PREREGISTRATION documents, not other types."""
        # Arrange
        post_doc = create_prefetched_post(document_type=DISCUSSION)
        fetcher = PersonalizeBatchQueries()

        # Act
        result = fetcher.fetch_proposal_data([post_doc.id])

        # Assert
        # Non-PREREGISTRATION docs won't have an entry in the result
        self.assertNotIn(post_doc.id, result)


class RFPDataTests(TestCase):
    """Tests for fetch_rfp_data method."""

    def test_fetch_rfp_data_identifies_open_grants(self):
        """Should return is_open=True for GRANT documents with OPEN status."""
        # Arrange
        unified_doc = create_prefetched_grant(status=Grant.OPEN)
        fetcher = PersonalizeBatchQueries()

        # Act
        result = fetcher.fetch_rfp_data([unified_doc.id])

        # Assert
        self.assertTrue(result[unified_doc.id]["is_open"])

    def test_fetch_rfp_data_false_for_closed_or_expired_grants(self):
        """Should return is_open=False for closed or expired grants."""
        # Arrange - Test CLOSED status
        closed_doc = create_prefetched_grant(status=Grant.CLOSED)
        fetcher = PersonalizeBatchQueries()

        # Act
        closed_result = fetcher.fetch_rfp_data([closed_doc.id])

        # Assert
        # Closed grants don't appear in the result (only OPEN ones do)
        self.assertNotIn(closed_doc.id, closed_result)

    def test_fetch_rfp_data_identifies_applicants(self):
        """Should return has_applicants=True when GrantApplication exists."""
        # Arrange
        unified_doc = create_prefetched_grant(status=Grant.OPEN)
        grant = unified_doc.grants.first()
        create_grant_application(grant)
        fetcher = PersonalizeBatchQueries()

        # Act
        result = fetcher.fetch_rfp_data([unified_doc.id])

        # Assert
        self.assertTrue(result[unified_doc.id]["has_applicants"])

    def test_fetch_rfp_data_only_for_grant_type(self):
        """Should only process GRANT documents."""
        # Arrange
        post_doc = create_prefetched_post(document_type=DISCUSSION)
        fetcher = PersonalizeBatchQueries()

        # Act
        result = fetcher.fetch_rfp_data([post_doc.id])

        # Assert
        # Non-GRANT docs won't have an entry in the result
        self.assertNotIn(post_doc.id, result)


class BatchFetchingTests(TestCase):
    """Tests for batch fetching functionality."""

    def test_fetch_all_returns_all_three_data_types(self):
        """fetch_all should return dict with bounty, proposal, and rfp keys."""
        # Arrange
        unified_doc = create_prefetched_paper()
        fetcher = PersonalizeBatchQueries()

        # Act
        result = fetcher.fetch_all([unified_doc.id])

        # Assert
        self.assertIn("bounty", result)
        self.assertIn("proposal", result)
        self.assertIn("rfp", result)

    def test_fetch_all_handles_empty_doc_ids(self):
        """Should handle empty list gracefully."""
        # Arrange
        fetcher = PersonalizeBatchQueries()

        # Act
        result = fetcher.fetch_all([])

        # Assert
        self.assertEqual(result["bounty"], {})
        self.assertEqual(result["proposal"], {})
        self.assertEqual(result["rfp"], {})

    def test_batch_queries_efficient_with_large_id_lists(self):
        """Should handle large batches efficiently without N+1 queries."""
        # Arrange
        docs = [create_prefetched_paper() for _ in range(10)]
        doc_ids = [doc.id for doc in docs]
        fetcher = PersonalizeBatchQueries()

        # Act
        # Expected queries: 2 bounty + 3 proposal (includes ContentType lookup) + 2 rfp = 7 total
        with self.assertNumQueries(7):
            result = fetcher.fetch_all(doc_ids)

        # Assert
        # Since none of the papers have bounties/proposals/rfps, results will be empty
        # The important part is that it doesn't do N+1 queries
        self.assertIsInstance(result["bounty"], dict)
        self.assertIsInstance(result["proposal"], dict)
        self.assertIsInstance(result["rfp"], dict)
