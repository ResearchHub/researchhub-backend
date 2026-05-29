from django.test import TestCase

from paper.related_models.paper_model import Paper
from paper.tests.helpers import create_paper
from user.tests.helpers import create_random_default_user


class PaperStatusTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("paper_status_user")

    def test_default_status_is_approved(self):
        # Act
        paper = create_paper(uploaded_by=self.user)

        # Assert
        self.assertEqual(paper.status, Paper.APPROVED)
        self.assertIsNone(paper.reviewed_by)
        self.assertIsNone(paper.reviewed_date)

    def test_status_choices_match_constants(self):
        # Assert
        self.assertEqual(
            set(dict(Paper.STATUS_CHOICES).keys()),
            {Paper.PENDING, Paper.APPROVED, Paper.DECLINED},
        )
