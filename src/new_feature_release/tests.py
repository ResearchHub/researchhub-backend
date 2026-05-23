from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from new_feature_release.models import NewFeatureClick
from user.tests.helpers import create_random_default_user


class NewFeatureViewSetTests(APITestCase):
    def setUp(self):
        self.user = create_random_default_user("feature-user")
        self.other_user = create_random_default_user("feature-other-user")
        self.client.force_authenticate(user=self.user)

    def test_queryset_only_exposes_current_users_feature_clicks(self):
        # Arrange
        own_click = NewFeatureClick.objects.create(
            user=self.user,
            feature="owned_feature",
        )
        other_click = NewFeatureClick.objects.create(
            user=self.other_user,
            feature="other_feature",
        )

        # Act
        list_response = self.client.get(reverse("new_feature_release-list"))
        detail_response = self.client.get(
            reverse("new_feature_release-detail", args=[other_click.id])
        )

        # Assert
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.status_code, status.HTTP_404_NOT_FOUND)

        result_ids = {item["id"] for item in list_response.data["results"]}
        self.assertEqual(result_ids, {own_click.id})

    def test_clicked_action_uses_current_user_scope(self):
        # Arrange
        feature = "shared_feature"
        url = reverse("new_feature_release-clicked")
        NewFeatureClick.objects.create(user=self.other_user, feature=feature)

        # Act
        response = self.client.get(url, {"feature": feature})

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"clicked": False})

        # Arrange
        NewFeatureClick.objects.create(user=self.user, feature=feature)

        # Act
        response = self.client.get(url, {"feature": feature})

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"clicked": True})

    def test_create_always_assigns_current_user(self):
        # Act
        response = self.client.post(
            reverse("new_feature_release-list"),
            {
                "feature": "spoofed_feature",
                "user": self.other_user.id,
            },
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        click = NewFeatureClick.objects.get(feature="spoofed_feature")
        self.assertEqual(click.user, self.user)
        self.assertEqual(response.data["user"], self.user.id)
