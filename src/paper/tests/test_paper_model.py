from django.test import TestCase

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
