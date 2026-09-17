from django.test import TestCase

from paper.related_models.authorship_model import Authorship
from paper.tests.helpers import create_paper
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_default_user


class PaperStatusTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("paper_status_user")

    def test_default_status_is_approved(self):
        # Act
        paper = create_paper(uploaded_by=self.user)

        # Assert
        unified_document = paper.unified_document
        self.assertEqual(unified_document.status, ResearchhubUnifiedDocument.APPROVED)
        self.assertIsNone(unified_document.reviewed_by)
        self.assertIsNone(unified_document.reviewed_date)

    def test_status_choices_match_constants(self):
        # Assert
        self.assertEqual(
            set(dict(ResearchhubUnifiedDocument.STATUS_CHOICES).keys()),
            {
                ResearchhubUnifiedDocument.PENDING,
                ResearchhubUnifiedDocument.APPROVED,
                ResearchhubUnifiedDocument.DECLINED,
            },
        )


class PaperBylineTests(TestCase):
    def test_orders_authors_by_byline_position(self):
        """The byline reads the first author, then middle authors, then the last."""
        # Arrange
        paper = create_paper(uploaded_by=create_random_default_user("byline_uploader"))
        last, first, middle = (
            create_random_default_user(name).author_profile
            for name in ("byline_last", "byline_first", "byline_middle")
        )
        for author, position in (
            (last, Authorship.LAST_AUTHOR_POSITION),
            (first, Authorship.FIRST_AUTHOR_POSITION),
            (middle, Authorship.MIDDLE_AUTHOR_POSITION),
        ):
            Authorship.objects.create(
                paper=paper, author=author, author_position=position
            )

        # Act
        ordered_authors = paper.ordered_authors

        # Assert
        self.assertEqual(ordered_authors, [first, middle, last])
