from django.test import TestCase, override_settings
from django.urls import include, path, reverse
from rest_framework import status
from rest_framework.routers import DefaultRouter
from rest_framework.test import APIClient
from rest_framework.viewsets import GenericViewSet

from discussion.constants.flag_reasons import NOT_SPECIFIED
from discussion.reaction_views import ReactionViewActionMixin
from discussion.serializers import FlagSerializer
from paper.related_models.paper_model import Paper
from user.related_models.user_model import User


# Dummy view for testing the mixin
class DummyPaperView(ReactionViewActionMixin, GenericViewSet):
    queryset = Paper.objects.all()
    serializer_class = FlagSerializer


# Register a router for testing the mixin
router = DefaultRouter()
router.register(r"dummy", DummyPaperView, basename="dummy")

urlpatterns = [
    path("api/", include(router.urls)),
]


@override_settings(ROOT_URLCONF=__name__)
class ReactionViewTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username="testUser1")
        self.paper = Paper.objects.create(title="testPaper1")

        # API client
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_flag(self):
        # Arrange
        url = reverse("dummy-flag", kwargs={"pk": self.paper.id})

        # Act
        response = self.client.post(
            url, {"reason": "Inappropriate", "reason_choice": NOT_SPECIFIED}
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_flag_already_flagged(self):
        # Arrange
        url = reverse("dummy-flag", kwargs={"pk": self.paper.id})

        # Act
        self.client.post(
            url, {"reason": "Inappropriate", "reason_choice": NOT_SPECIFIED}
        )
        response = self.client.post(
            url, {"reason": "Inappropriate", "reason_choice": NOT_SPECIFIED}
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
