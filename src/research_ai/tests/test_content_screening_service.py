from unittest.mock import Mock

from django.test import TestCase

from discussion.constants.flag_reasons import SPAM
from research_ai.models import ContentScreening
from research_ai.services.content_screening_service import (
    COMMENT_QUESTIONS,
    FLAG_THRESHOLD,
    ContentScreeningService,
)
from research_ai.services.jev_client import MODEL, Decision
from researchhub_comment.tests.helpers import create_rh_comment
from user.constants.risk_score_constants import TRUSTED_THRESHOLD
from user.models import RiskScore, User
from user.related_models.user_model import AI_EXPERT_EMAIL


def _mock_jev_client(**answers: float) -> Mock:
    """Build a Jev client that scores every question 0.1 unless given a score."""
    client = Mock()
    client.decide.return_value = Decision(
        model=MODEL,
        answers={name: 0.1 for name in COMMENT_QUESTIONS} | answers,
        cost_microusd=None,
    )
    return client


class ContentScreeningServiceTests(TestCase):
    def setUp(self) -> None:
        """Create the AI account that files flags and a comment to screen."""
        self.flagger = User.objects.create_user(
            username=AI_EXPERT_EMAIL, email=AI_EXPERT_EMAIL
        )
        self.comment = create_rh_comment()

    def test_records_every_result_and_flags_only_those_at_the_threshold(self) -> None:
        """Every result is recorded, but only a score at the threshold files a flag."""
        for promotional, should_flag in ((FLAG_THRESHOLD, True), (0.5, False)):
            with self.subTest(promotional=promotional):
                # Arrange
                self.comment.flags.all().delete()
                ContentScreening.objects.all().delete()
                client = _mock_jev_client(promotional=promotional)

                # Act
                ContentScreeningService(client=client).screen_comment(self.comment)

                # Assert
                screening = ContentScreening.objects.get()
                is_flagged = self.comment.flags.filter(
                    created_by=self.flagger, reason_choice=SPAM
                ).exists()
                self.assertEqual(screening.item, self.comment)
                self.assertEqual(screening.scores["promotional"], promotional)
                self.assertEqual(screening.flagged, should_flag)
                self.assertEqual(is_flagged, should_flag)

    def test_skips_comments_from_trusted_users(self) -> None:
        """A trusted user's comment is neither screened nor flagged."""
        # Arrange
        RiskScore.objects.create(user=self.comment.created_by, score=TRUSTED_THRESHOLD)
        client = _mock_jev_client(promotional=0.99)

        # Act
        ContentScreeningService(client=client).screen_comment(self.comment)

        # Assert
        client.decide.assert_not_called()
        self.assertFalse(self.comment.flags.exists())

    def test_rescreens_flagged_comments_without_flagging_them_again(self) -> None:
        """Rescreening a flagged comment records it but files no second flag."""
        # Arrange
        client = _mock_jev_client(promotional=0.99)
        service = ContentScreeningService(client=client)
        service.screen_comment(self.comment)

        # Act
        service.screen_comment(self.comment)

        # Assert
        self.assertEqual(ContentScreening.objects.count(), 2)
        self.assertEqual(self.comment.flags.count(), 1)
