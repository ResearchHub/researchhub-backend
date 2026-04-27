from unittest.mock import patch

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from hub.models import Hub
from hub.tests.helpers import create_hub
from paper.tests.helpers import create_paper
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.tests.helpers import create_rh_comment
from researchhub_document.helpers import create_post
from review.models import Review
from user.tests.helpers import create_random_default_user


class ModelTests(TestCase):
    """Tests for ResearchhubUnifiedDocument model methods"""

    def setUp(self):
        self.user = create_random_default_user("test_user")
        self.paper = create_paper(uploaded_by=self.user)

    def test_get_journal_returns_none_when_no_journal_hubs(self):
        """Test that get_journal returns None when document has no journal hubs"""
        regular_hub = create_hub("Regular Hub")
        self.paper.unified_document.hubs.add(regular_hub)

        result = self.paper.unified_document.get_journal()

        self.assertIsNone(result)

    @patch.object(settings, "RESEARCHHUB_JOURNAL_ID", "999999")
    def test_get_journal_returns_journal_hub(self):
        """Test that get_journal returns a journal hub when one exists"""
        journal_hub = create_hub("Nature", namespace=Hub.Namespace.JOURNAL)
        self.paper.unified_document.hubs.add(journal_hub)

        result = self.paper.unified_document.get_journal()

        self.assertEqual(result, journal_hub)

    def test_get_journal_prioritizes_researchhub_journal(self):
        """Test that get_journal prioritizes ResearchHub Journal over other journals"""
        other_journal = create_hub("Other Journal", namespace=Hub.Namespace.JOURNAL)
        rh_journal = create_hub("ResearchHub Journal", namespace=Hub.Namespace.JOURNAL)
        self.paper.unified_document.hubs.add(other_journal)
        self.paper.unified_document.hubs.add(rh_journal)

        with patch.object(settings, "RESEARCHHUB_JOURNAL_ID", str(rh_journal.id)):
            result = self.paper.unified_document.get_journal()

        self.assertEqual(result, rh_journal)

    @patch.object(settings, "RESEARCHHUB_JOURNAL_ID", "999999")
    def test_get_journal_prioritizes_preprint(self):
        """Test that get_journal prioritizes biorxiv preprint server"""
        other_journal = create_hub("Other Journal", namespace=Hub.Namespace.JOURNAL)
        biorxiv = Hub.objects.create(
            name="bioRxiv", slug="biorxiv", namespace=Hub.Namespace.JOURNAL
        )
        self.paper.unified_document.hubs.add(other_journal)
        self.paper.unified_document.hubs.add(biorxiv)

        result = self.paper.unified_document.get_journal()

        self.assertEqual(result, biorxiv)

    @patch.object(settings, "RESEARCHHUB_JOURNAL_ID", "999999")
    def test_get_journal_ignores_non_journal_hubs(self):
        """Test that get_journal ignores hubs without JOURNAL namespace"""
        category_hub = create_hub("Category Hub", namespace=Hub.Namespace.CATEGORY)
        journal_hub = create_hub("Science", namespace=Hub.Namespace.JOURNAL)
        self.paper.unified_document.hubs.add(category_hub)
        self.paper.unified_document.hubs.add(journal_hub)

        result = self.paper.unified_document.get_journal()

        self.assertEqual(result, journal_hub)

    def test_get_review_details_only_counts_assessed_reviews(self):
        """Only reviews with is_assessed=True are included in avg/count."""
        # Arrange
        post = create_post(created_by=self.user)
        unified_doc = post.unified_document
        comment_ct = ContentType.objects.get_for_model(RhCommentModel)

        # Two assessed reviews (scores 5 and 3) and one unassessed review (score 1)
        for score, is_assessed in [(5, True), (3, True), (1, False)]:
            comment = create_rh_comment(post=post, created_by=self.user)
            Review.objects.create(
                created_by=self.user,
                content_type=comment_ct,
                object_id=comment.id,
                unified_document=unified_doc,
                score=score,
                is_assessed=is_assessed,
            )

        # Act
        details = unified_doc.get_review_details()

        # Assert
        self.assertEqual(details["count"], 2)
        self.assertEqual(details["avg"], 4.0)

    def test_get_review_details_returns_zero_when_no_assessed_reviews(self):
        """Returns avg=0/count=0 when no assessed reviews exist."""
        # Arrange
        post = create_post(created_by=self.user)
        unified_doc = post.unified_document
        comment = create_rh_comment(post=post, created_by=self.user)
        Review.objects.create(
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(comment),
            object_id=comment.id,
            unified_document=unified_doc,
            score=4,
            is_assessed=False,
        )

        # Act
        details = unified_doc.get_review_details()

        # Assert
        self.assertEqual(details["count"], 0)
        self.assertEqual(details["avg"], 0)
