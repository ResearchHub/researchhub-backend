from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from feed.models import FeedEntry
from paper.related_models.paper_model import Paper
from researchhub_document.tasks import recalc_hot_score_task
from user.related_models.user_model import User


class TaskTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username="user1")
        self.paper = Paper.objects.create(title="paper1")
        self.paper_content_type = ContentType.objects.get_for_model(Paper)

    @patch(
        "researchhub_document.related_models.researchhub_unified_document_model.ResearchhubUnifiedDocument.calculate_hot_score"
    )
    def test_recalc_hot_score_task(self, mock_calculate_hot_score):
        # Arrange
        mock_calculate_hot_score.return_value = (5, True)

        # Act
        recalc_hot_score_task(self.paper_content_type.id, self.paper.id)

        # Assert
        mock_calculate_hot_score.assert_called_once_with(should_save=True)

    @patch(
        "researchhub_document.related_models.researchhub_unified_document_model.ResearchhubUnifiedDocument.calculate_hot_score"
    )
    def test_recalc_hot_score_task_with_feed_entries(self, mock_calculate_hot_score):
        # Arrange
        mock_calculate_hot_score.return_value = (5, True)
        self.paper.unified_document.feed_entries.create(
            content_type=self.paper_content_type,
            object_id=self.paper.id,
            content={},
            action=FeedEntry.OPEN,
            action_date=timezone.now(),
            user=self.user,
        )
        self.paper.unified_document.feed_entries.create(
            content_type=self.paper_content_type,
            object_id=self.paper.id,
            content={},
            action=FeedEntry.PUBLISH,
            action_date=timezone.now(),
            user=self.user,
        )

        # Act
        recalc_hot_score_task(self.paper_content_type.id, self.paper.id)

        # Assert
        for entry in self.paper.unified_document.feed_entries.all():
            self.assertEqual(entry.hot_score, 5)
        mock_calculate_hot_score.assert_called_once_with(should_save=True)
