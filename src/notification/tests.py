from unittest.mock import AsyncMock, MagicMock

import redis
from django.db import transaction
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from notification.models import Notification
from notification.services import NotificationService
from paper.tests.helpers import create_paper
from user.tests.helpers import create_random_default_user
from utils.test_helpers import AWSMockTransactionTestCase


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


class NotificationServiceTests(AWSMockTransactionTestCase):
    """Verify notification persistence and post-commit delivery behavior."""

    def setUp(self) -> None:
        """Create a notification audience and mock its external transports."""
        super().setUp()
        self.recipient = create_random_default_user("recipient")
        self.actor = create_random_default_user("actor")
        self.paper = create_paper(uploaded_by=self.actor)
        self.layer = MagicMock()
        self.layer.group_send = AsyncMock()
        self.service = NotificationService(channel_layer=self.layer)

    def test_preserves_one_notification_when_the_socket_fails(self) -> None:
        """A failed socket send leaves one inbox row and does not interrupt commit."""
        # Arrange
        self.layer.group_send.side_effect = redis.ConnectionError("Unavailable")

        # Act
        with (
            self.assertLogs("notification.services.notification_service", "WARNING"),
            transaction.atomic(),
        ):
            notification = self.service.send_once(
                Notification.PUBLICATIONS_ADDED,
                recipient=self.recipient,
                action_user=self.actor,
                item=self.paper,
                unified_document=self.paper.unified_document,
            )
            repeated = self.service.send_once(
                Notification.PUBLICATIONS_ADDED,
                recipient=self.recipient,
                action_user=self.actor,
                item=self.paper,
            )
            self.layer.group_send.assert_not_awaited()

        # Assert
        self.assertIsNone(repeated)
        self.assertEqual(
            Notification.objects.filter(recipient=self.recipient).count(), 1
        )
        self.layer.group_send.assert_awaited_once()
        group, message = self.layer.group_send.call_args.args
        self.assertEqual(group, f"notification_{self.recipient.id}")
        self.assertEqual(message["type"], "send_notification")
        self.assertEqual(message["data"]["id"], notification.id)
        self.assertEqual(
            set(message["data"]),
            {
                "action_user",
                "body",
                "created_date",
                "extra",
                "id",
                "notification_type",
                "read",
                "read_date",
                "recipient",
            },
        )

    def test_discards_delivery_when_the_transaction_rolls_back(self) -> None:
        """A rolled-back domain action creates no notification or external message."""
        # Arrange
        initial_count = Notification.objects.count()

        # Act
        with transaction.atomic():
            self.service.send(
                Notification.PUBLICATIONS_ADDED,
                recipient=self.recipient,
                action_user=self.actor,
                item=self.paper,
            )
            transaction.set_rollback(True)

        # Assert
        self.assertEqual(Notification.objects.count(), initial_count)
        self.layer.group_send.assert_not_awaited()
