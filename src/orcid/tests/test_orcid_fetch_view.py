from unittest.mock import Mock

from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from orcid.tests.helpers import OrcidTestHelper
from orcid.views import OrcidFetchView
from user.related_models.user_model import User
from user.tests.helpers import create_random_default_user


class OrcidFetchViewTests(TestCase):

    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = OrcidFetchView.as_view()
        self.user = create_random_default_user("u")
        self.mock_task = Mock()

    def test_unauthenticated_rejected(self):
        # Arrange
        request = self.factory.post("/")

        # Act
        response = self.view(request, sync_task=self.mock_task)

        # Assert
        self.assertEqual(response.status_code, 401)

    def test_missing_author_returns_400(self):
        # Arrange
        self.user.author_profile.delete()
        self.user = User.objects.get(id=self.user.id)
        request = self.factory.post("/")
        force_authenticate(request, user=self.user)

        # Act
        response = self.view(request, sync_task=self.mock_task)

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"], "Author profile not found")

    def test_orcid_not_connected_returns_400(self):
        # Arrange
        request = self.factory.post("/")
        force_authenticate(request, user=self.user)

        # Act
        response = self.view(request, sync_task=self.mock_task)

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"], "ORCID not connected")

    def test_sync_starts_when_connected(self):
        # Arrange
        SocialAccount.objects.create(user=self.user, provider=OrcidProvider.id, uid=OrcidTestHelper.ORCID_ID)
        request = self.factory.post("/")
        force_authenticate(request, user=self.user)

        # Act
        response = self.view(request, sync_task=self.mock_task)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.mock_task.delay.assert_called_once_with(self.user.author_profile.id)
