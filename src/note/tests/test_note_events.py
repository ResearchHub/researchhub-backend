from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from note.models import NoteContent
from note.services.note_events import (
    EVENT_TYPE,
    NOTE_VERSION_CREATED,
    NoteVersionEventPublisher,
    note_group,
)
from note.tests.helpers import create_note


class FakeChannelLayer:
    """Records group_send calls; optionally fails like a down Redis."""

    def __init__(self, error: Exception | None = None):
        self.sent = []
        self._error = error

    async def group_send(self, group, message):
        if self._error is not None:
            raise self._error
        self.sent.append((group, message))


class NoteVersionEventPublisherTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="events@researchhub_test.com",
            password="password",
            email="events@researchhub_test.com",
        )
        self.note, self.seed_version = create_note(self.user, organization=None)

    def _create_version(self, **kwargs):
        return NoteContent.objects.create(note=self.note, plain_text="v2", **kwargs)

    def test_publish_sends_the_full_payload_after_commit(self):
        # Arrange
        layer = FakeChannelLayer()
        publisher = NoteVersionEventPublisher(channel_layer=layer)
        version = self._create_version(
            created_by=self.user,
            created_via=NoteContent.CREATED_VIA_EDITOR,
            parent_version=self.seed_version,
        )

        # Act
        with self.captureOnCommitCallbacks(execute=True):
            publisher.publish_created(version)
            # Deferred: nothing may be pushed before the transaction commits,
            # or a nudged refetch could read state that is not visible yet.
            self.assertEqual(layer.sent, [])

        # Assert
        self.assertEqual(
            layer.sent,
            [
                (
                    note_group(self.note.id),
                    {
                        "type": EVENT_TYPE,
                        "data": {
                            "type": NOTE_VERSION_CREATED,
                            "note_id": self.note.id,
                            "version_id": version.id,
                            "parent_version_id": self.seed_version.id,
                            "created_by": self.user.id,
                            "created_via": NoteContent.CREATED_VIA_EDITOR,
                            "created_date": version.created_date.isoformat(),
                        },
                    },
                )
            ],
        )


class NoteVersionCreatedSignalTests(TestCase):
    """Every committed NoteContent row emits, whoever created it."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="signal@researchhub_test.com",
            password="password",
            email="signal@researchhub_test.com",
        )
        self.note, self.seed_version = create_note(self.user, organization=None)

    def test_a_failing_channel_layer_never_breaks_the_write(self):
        # Arrange
        layer = FakeChannelLayer(error=RuntimeError("redis down"))

        # Act: the version write goes through even though every publish fails.
        with (
            patch(
                "notification.services.notification_service.get_channel_layer",
                return_value=layer,
            ),
            self.assertLogs(
                "notification.services.notification_service", level="WARNING"
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            version = NoteContent.objects.create(note=self.note, plain_text="v2")

        # Assert
        self.note.refresh_from_db()
        self.assertEqual(self.note.latest_version_id, version.id)

    def test_updating_a_version_does_not_publish(self):
        # Arrange
        layer = FakeChannelLayer()

        # Act: only creation signals a new version.
        with (
            patch(
                "notification.services.notification_service.get_channel_layer",
                return_value=layer,
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.seed_version.plain_text = "edited in place"
            self.seed_version.save()

        # Assert
        self.assertEqual(layer.sent, [])
