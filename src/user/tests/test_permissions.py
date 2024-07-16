from django.test import TestCase
from user.tests.helpers import (
    create_random_authenticated_user,
)
from user.models import UserVerification
from rest_framework.response import Response
from rest_framework.views import APIView
from user.permissions import IsVerifiedUser
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate
from rest_framework import status


class PermissionsTests(TestCase):

    class TestView(APIView):
        permission_classes = [IsVerifiedUser]

        def get(self, request):
            return Response({"noop"})

    def setUp(self):
        self.verified_user = create_random_authenticated_user("verified_user")
        UserVerification.objects.create(
            user=self.verified_user,
            status=UserVerification.Status.APPROVED,
        )
        self.declined_user = create_random_authenticated_user("declined_user")
        UserVerification.objects.create(
            user=self.declined_user,
            status=UserVerification.Status.DECLINED,
        )
        self.unverified_user = create_random_authenticated_user("unverified_user")

        self.client = APIClient()
        self.factory = APIRequestFactory()

    def test_is_verified_user(self):
        # Arrange
        request = self.factory.get("/test-view/")
        force_authenticate(request, user=self.verified_user)
        view = PermissionsTests.TestView.as_view()

        # Act
        response = view(request)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_is_declined_user(self):
        # Arrange
        request = self.factory.get("/test-view/")
        force_authenticate(request, user=self.declined_user)
        view = PermissionsTests.TestView.as_view()

        # Act
        response = view(request)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_is_unverified_user(self):
        # Arrange
        request = self.factory.get("/test-view/")
        force_authenticate(request, user=self.unverified_user)
        view = PermissionsTests.TestView.as_view()

        # Act
        response = view(request)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
