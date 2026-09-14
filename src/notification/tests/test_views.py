from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from notification.models import Notification
from paper.tests.helpers import create_paper
from user.tests.helpers import create_random_default_user


class NotificationViewSetTests(APITestCase):
    def setUp(self):
        self.user = create_random_default_user("testuser")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.paper = create_paper(uploaded_by=self.user)

        self.read_notification = Notification.objects.create(
            recipient=self.user,
            action_user=self.user,
            notification_type=Notification.PUBLICATIONS_ADDED,
            read=True,
            item=self.paper,
        )

        self.unread_notification = Notification.objects.create(
            recipient=self.user,
            action_user=self.user,
            notification_type=Notification.PUBLICATIONS_ADDED,
            read=False,
            item=self.paper,
        )

        self.unread_notification2 = Notification.objects.create(
            recipient=self.user,
            action_user=self.user,
            notification_type=Notification.PUBLICATIONS_ADDED,
            read=False,
            item=self.paper,
        )

    def test_get_unread_count(self):
        url = reverse("notification-unread-count")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)

    def test_get_unread_count_unauthenticated(self):
        self.client.force_authenticate(user=None)
        url = reverse("notification-unread-count")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
