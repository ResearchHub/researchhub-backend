from django.test import TestCase, override_settings
from django.urls import include, path, reverse
from rest_framework import status
from rest_framework.routers import DefaultRouter
from rest_framework.test import APIClient
from rest_framework.viewsets import GenericViewSet

from discussion.models import Interest
from discussion.serializers import InterestSerializer
from discussion.tests.helpers import create_interest
from discussion.views import ReactionViewActionMixin, create_or_get_interest
from paper.related_models.paper_model import Paper
from researchhub_document.models import ResearchhubPost
from user.related_models.user_model import User


# Dummy view for testing the mixin
class DummyPaperView(ReactionViewActionMixin, GenericViewSet):
    queryset = Paper.objects.all()
    serializer_class = InterestSerializer


# Register a router for testing the mixin
router = DefaultRouter()
router.register(r"dummy", DummyPaperView, basename="dummy")

urlpatterns = [
    path("api/", include(router.urls)),
]


@override_settings(ROOT_URLCONF=__name__)
class InterestViewTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username="testUser1")
        self.paper = Paper.objects.create(title="testPaper1")

        # API client
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_mark_not_interested_creates_new_interest(self):
        # Arrange
        url = reverse("dummy-mark-not-interested", kwargs={"pk": self.paper.id})

        # Act
        response = self.client.post(url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Interest.objects.count(), 1)

        interest = Interest.objects.first()
        self.assertEqual(interest.created_by, self.user)
        self.assertEqual(interest.item, self.paper)
        self.assertEqual(interest.interest_type, Interest.DISMISSED)

    def test_mark_not_interested_returns_existing_interest(self):
        # Arrange
        url = reverse("dummy-mark-not-interested", kwargs={"pk": self.paper.id})

        # Create existing interest
        existing_interest = create_interest(self.user, self.paper)

        # Act
        response = self.client.post(url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Interest.objects.count(), 1)
        self.assertEqual(response.data["id"], existing_interest.id)

    def test_mark_not_interested_requires_authentication(self):
        # Arrange
        url = reverse("dummy-mark-not-interested", kwargs={"pk": self.paper.id})
        self.client.force_authenticate(user=None)

        # Act
        response = self.client.post(url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_mark_not_interested_with_different_content_types(self):
        # Test with ResearchhubPost
        post = ResearchhubPost.objects.create(
            title="Test Post", created_by=self.user, unified_document_id=1
        )

        # Create a dummy view for posts
        class DummyPostView(ReactionViewActionMixin, GenericViewSet):
            queryset = ResearchhubPost.objects.all()
            serializer_class = InterestSerializer

        # Register the post router
        post_router = DefaultRouter()
        post_router.register(r"dummy_post", DummyPostView, basename="dummy_post")

        post_urlpatterns = [
            path("api/", include(post_router.urls)),
        ]

        with override_settings(ROOT_URLCONF=__name__):
            # Update urlpatterns to include post router
            urlpatterns.extend(post_urlpatterns)

            url = reverse("dummy_post-mark-not-interested", kwargs={"pk": post.id})
            response = self.client.post(url)

            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(Interest.objects.count(), 1)

    def test_create_or_get_interest_helper_function(self):
        # Test creating new interest
        interest, created = create_or_get_interest(self.user, self.paper)
        self.assertTrue(created)
        self.assertEqual(interest.created_by, self.user)
        self.assertEqual(interest.item, self.paper)
        self.assertEqual(interest.interest_type, Interest.DISMISSED)

        # Test getting existing interest
        interest2, created2 = create_or_get_interest(self.user, self.paper)
        self.assertFalse(created2)
        self.assertEqual(interest.id, interest2.id)

    def test_interest_serializer(self):
        # Arrange
        interest = create_interest(self.user, self.paper)

        # Act
        serializer = InterestSerializer(interest)

        # Assert
        data = serializer.data
        self.assertIn("id", data)
        self.assertIn("content_type", data)
        self.assertIn("created_by", data)
        self.assertIn("created_date", data)
        self.assertIn("item", data)
        self.assertIn("object_id", data)
        self.assertIn("interest_type", data)
        self.assertEqual(data["interest_type"], Interest.DISMISSED)

    def test_interest_model_str_representation(self):
        # Arrange
        interest = create_interest(self.user, self.paper)

        # Act
        str_repr = str(interest)

        # Assert
        self.assertIn(str(self.user), str_repr)
        self.assertIn("Dismissed", str_repr)

    def test_interest_unique_constraint(self):
        # Arrange
        create_interest(self.user, self.paper)

        # Act & Assert
        # Creating another interest with same user and item should raise IntegrityError
        with self.assertRaises(Exception):  # IntegrityError or similar
            Interest.objects.create(
                created_by=self.user, item=self.paper, interest_type=Interest.DISMISSED
            )
