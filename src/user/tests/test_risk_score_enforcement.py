from django.test import TestCase
from rest_framework.test import APITestCase

from hub.tests.helpers import create_hub
from researchhub_document.views.researchhub_post_views import (
    MIN_POST_BODY_LENGTH,
    MIN_POST_TITLE_LENGTH,
)
from user.constants.risk_score_constants import (
    DEFAULT_SCORE,
    RESTRICTED_THRESHOLD,
    TRUSTED_THRESHOLD,
)
from user.related_models.risk_score_model import RiskScore
from user.services.risk_score_service import RiskScoreService
from user.tests.helpers import create_random_default_user, make_user_verified
from utils.models import ModeratedDocumentMixin


def _set_score(user, score):
    RiskScore.objects.update_or_create(user=user, defaults={"score": score})


class InitialWorkStatusTests(TestCase):
    def setUp(self):
        self.service = RiskScoreService()
        self.user = create_random_default_user("ws")

    def test_trusted_user_auto_approves(self):
        # Arrange
        _set_score(self.user, TRUSTED_THRESHOLD)

        # Act / Assert
        self.assertEqual(
            self.service.initial_work_status(self.user),
            ModeratedDocumentMixin.APPROVED,
        )

    def test_normal_user_enters_queue(self):
        # Arrange
        _set_score(self.user, DEFAULT_SCORE)

        # Act / Assert
        self.assertEqual(
            self.service.initial_work_status(self.user),
            ModeratedDocumentMixin.PENDING,
        )


class PostCreationGatingTests(APITestCase):
    def setUp(self):
        self.user = create_random_default_user("gating")
        make_user_verified(self.user)
        self.hub = create_hub("gating-hub")
        self.client.force_authenticate(self.user)

    def _create_post(self):
        return self.client.post(
            "/api/researchhubpost/",
            {
                "document_type": "DISCUSSION",
                "created_by": self.user.id,
                "full_src": "body",
                "is_public": True,
                "renderable_text": "x" * MIN_POST_BODY_LENGTH,
                "title": "x" * MIN_POST_TITLE_LENGTH,
                "hubs": [self.hub.id],
            },
        )

    def test_normal_user_post_enters_queue(self):
        # Arrange
        _set_score(self.user, DEFAULT_SCORE)

        # Act
        response = self._create_post()

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], ModeratedDocumentMixin.PENDING)

    def test_trusted_user_post_auto_approves(self):
        # Arrange
        _set_score(self.user, TRUSTED_THRESHOLD)

        # Act
        response = self._create_post()

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], ModeratedDocumentMixin.APPROVED)

    def test_restricted_user_post_enters_queue(self):
        # Arrange
        _set_score(self.user, RESTRICTED_THRESHOLD)

        # Act
        response = self._create_post()

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], ModeratedDocumentMixin.PENDING)
