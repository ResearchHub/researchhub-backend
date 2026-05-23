from unittest.mock import Mock, patch

from django.test import TestCase

from user.events import (
    UserReinstatedEvent,
    UserSuspendedEvent,
    user_reinstated,
    user_suspended,
)
from user.models import User


class UserSearchDocumentUpdateSignalTests(TestCase):
    @patch("search.signals.user_events.update_user_related_documents.delay")
    def test_user_suspended_event_schedules_update(self, delay_mock: Mock):
        # Arrange
        event = UserSuspendedEvent(user_id=123)

        # Act
        user_suspended.send(
            sender=User,
            event=event,
        )

        # Assert
        delay_mock.assert_called_once_with(123)

    @patch("search.signals.user_events.update_user_related_documents.delay")
    def test_user_reinstated_event_schedules_update(self, delay_mock: Mock):
        # Arrange
        event = UserReinstatedEvent(user_id=123)

        # Act
        user_reinstated.send(sender=User, event=event)

        # Assert
        delay_mock.assert_called_once_with(123)
