from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from rest_framework.test import APIRequestFactory, APITestCase

from hub.tests.helpers import create_hub
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.views.researchhub_post_views import (
    MIN_POST_BODY_LENGTH,
    MIN_POST_TITLE_LENGTH,
)
from user.permissions import IsNotRestricted
from user.related_models.risk_score_model import RiskScore
from user.services.risk_score_service import RiskScoreService
from user.tests.helpers import create_random_default_user, make_user_verified
from utils.models import ModeratedDocumentMixin
from utils.permissions import CreateOrUpdateIfAllowed

NORMAL = 100
RESTRICTED = 10


def _set_score(user, score):
    RiskScore.objects.update_or_create(user=user, defaults={"score": score})


class InitialWorkStatusTests(TestCase):
    def setUp(self):
        self.service = RiskScoreService()
        self.user = create_random_default_user("ws")

    def test_trusted_user_auto_approves(self):
        # Arrange
        _set_score(self.user, 200)

        # Act / Assert
        self.assertEqual(
            self.service.initial_work_status(self.user),
            ModeratedDocumentMixin.APPROVED,
        )

    def test_normal_user_enters_queue(self):
        # Arrange
        _set_score(self.user, NORMAL)

        # Act / Assert
        self.assertEqual(
            self.service.initial_work_status(self.user),
            ModeratedDocumentMixin.PENDING,
        )


class IsNotRestrictedTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.permission = IsNotRestricted()
        self.user = create_random_default_user("restricted")

    def _request(self, method="post", user=None):
        request = getattr(self.factory, method)("/")
        request.user = self.user if user is None else user
        return request

    def test_restricted_user_blocked_on_write(self):
        # Arrange
        _set_score(self.user, RESTRICTED)

        # Act / Assert
        self.assertFalse(self.permission.has_permission(self._request("post"), None))

    def test_normal_user_allowed_on_write(self):
        # Arrange
        _set_score(self.user, NORMAL)

        # Act / Assert
        self.assertTrue(self.permission.has_permission(self._request("post"), None))

    def test_read_always_allowed(self):
        # Arrange
        _set_score(self.user, RESTRICTED)

        # Act / Assert
        self.assertTrue(self.permission.has_permission(self._request("get"), None))

    def test_anonymous_deferred_to_other_permissions(self):
        # Act / Assert
        self.assertTrue(
            self.permission.has_permission(
                self._request("post", user=AnonymousUser()), None
            )
        )


class CreateOrUpdateIfAllowedRestrictionTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.permission = CreateOrUpdateIfAllowed()
        self.user = create_random_default_user("cou")

    def _write_request(self):
        request = self.factory.post("/")
        request.user = self.user
        return request

    def test_restricted_user_blocked(self):
        # Arrange
        _set_score(self.user, RESTRICTED)

        # Act / Assert
        self.assertFalse(self.permission.has_permission(self._write_request(), None))

    def test_normal_user_allowed(self):
        # Arrange
        _set_score(self.user, NORMAL)

        # Act / Assert
        self.assertTrue(self.permission.has_permission(self._write_request(), None))


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
        _set_score(self.user, NORMAL)

        # Act
        response = self._create_post()

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], ResearchhubPost.PENDING)

    def test_trusted_user_post_auto_approves(self):
        # Arrange
        _set_score(self.user, 200)

        # Act
        response = self._create_post()

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], ResearchhubPost.APPROVED)

    def test_restricted_user_blocked(self):
        # Arrange
        _set_score(self.user, RESTRICTED)

        # Act
        response = self._create_post()

        # Assert
        self.assertEqual(response.status_code, 403)
