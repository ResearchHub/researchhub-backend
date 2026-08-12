import json

from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.contenttypes.models import ContentType
from django.test import TransactionTestCase

import note.routing
from note.consumers import CLOSE_NOT_FOUND, CLOSE_UNAUTHENTICATED
from note.models import NoteContent
from note.services.note_events import EVENT_TYPE, NOTE_VERSION_CREATED, note_group
from note.tests.helpers import create_note
from researchhub_access_group.constants import ADMIN, MEMBER, VIEWER
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubUnifiedDocument
from user.models import Organization

application = URLRouter(note.routing.websocket_urlpatterns)


class NoteVersionConsumerTests(TransactionTestCase):
    """Admission matches the note's read permissions; events forwarded verbatim.

    The communicator's scope user is set directly, standing in for what
    ``TokenAuthMiddlewareStack`` resolves in production. All database
    arrangement lives in ``setUp``: the async test bodies must not touch the
    ORM synchronously, and the consumer does its own reads through
    ``database_sync_to_async`` -- which also forces ``TransactionTestCase``
    here, because its connection cleanup closes the wrapping transaction a
    plain ``TestCase`` keeps open across the whole test.
    """

    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            username="owner@researchhub_test.com",
            password="password",
            email="owner@researchhub_test.com",
        )
        self.viewer = user_model.objects.create_user(
            username="viewer@researchhub_test.com",
            password="password",
            email="viewer@researchhub_test.com",
        )
        self.org_member = user_model.objects.create_user(
            username="member@researchhub_test.com",
            password="password",
            email="member@researchhub_test.com",
        )
        self.outsider = user_model.objects.create_user(
            username="outsider@researchhub_test.com",
            password="password",
            email="outsider@researchhub_test.com",
        )

        self.note, self.seed_version = create_note(self.owner, organization=None)
        doc_ct = ContentType.objects.get_for_model(ResearchhubUnifiedDocument)
        Permission.objects.create(
            access_type=ADMIN,
            content_type=doc_ct,
            object_id=self.note.unified_document.id,
            user=self.owner,
        )
        # Read-only user permission: enough for the socket, like the note
        # detail.
        Permission.objects.create(
            access_type=VIEWER,
            content_type=doc_ct,
            object_id=self.note.unified_document.id,
            user=self.viewer,
        )
        # Org-mediated read: the note is shared with an organization the
        # member belongs to.
        self.organization = Organization.objects.create(name="note events org")
        org_ct = ContentType.objects.get_for_model(Organization)
        Permission.objects.create(
            access_type=MEMBER,
            content_type=org_ct,
            object_id=self.organization.id,
            user=self.org_member,
        )
        Permission.objects.create(
            access_type=MEMBER,
            content_type=doc_ct,
            object_id=self.note.unified_document.id,
            organization=self.organization,
            user=self.owner,
        )

        # A soft-deleted note reads as missing.
        self.removed_note = create_note(self.owner, organization=None)[0]
        self.removed_note.unified_document.is_removed = True
        self.removed_note.unified_document.save(update_fields=["is_removed"])

    async def _connect(self, user, *, note_id=None):
        note_id = self.note.id if note_id is None else note_id
        communicator = WebsocketCommunicator(
            application, f"/ws/notebook/notes/{note_id}/"
        )
        communicator.scope["user"] = user
        connected, detail = await communicator.connect()
        return communicator, connected, detail

    async def test_anonymous_connection_is_rejected(self):
        # Act
        _communicator, connected, code = await self._connect(AnonymousUser())

        # Assert
        self.assertFalse(connected)
        self.assertEqual(code, CLOSE_UNAUTHENTICATED)

    async def test_deactivated_account_is_rejected(self):
        # Arrange: the account is disabled but its token still resolves, the
        # state the auth middleware hands over for a lingering token.
        self.owner.is_active = False
        await self.owner.asave(update_fields=["is_active"])

        # Act
        _communicator, connected, code = await self._connect(self.owner)

        # Assert
        self.assertFalse(connected)
        self.assertEqual(code, CLOSE_UNAUTHENTICATED)

    async def test_user_without_read_access_reads_as_not_found(self):
        # Act: authenticated, but no user- or org-level permission.
        _communicator, connected, code = await self._connect(self.outsider)

        # Assert
        self.assertFalse(connected)
        self.assertEqual(code, CLOSE_NOT_FOUND)

    async def test_missing_note_reads_as_not_found(self):
        # Act
        _communicator, connected, code = await self._connect(self.owner, note_id=999999)

        # Assert
        self.assertFalse(connected)
        self.assertEqual(code, CLOSE_NOT_FOUND)

    async def test_soft_deleted_note_reads_as_not_found(self):
        # Act: even the owner cannot watch a removed note.
        _communicator, connected, code = await self._connect(
            self.owner, note_id=self.removed_note.id
        )

        # Assert
        self.assertFalse(connected)
        self.assertEqual(code, CLOSE_NOT_FOUND)

    async def test_read_only_viewer_is_admitted(self):
        # Act: the gate is the note's read permission, not the editing one.
        communicator, connected, subprotocol = await self._connect(self.viewer)

        # Assert
        self.assertTrue(connected)
        self.assertEqual(subprotocol, "Token")
        await communicator.disconnect()

    async def test_org_member_is_admitted_through_the_org_permission(self):
        # Act
        communicator, connected, _detail = await self._connect(self.org_member)

        # Assert
        self.assertTrue(connected)
        await communicator.disconnect()

    async def test_subscriber_receives_published_events(self):
        # Arrange
        communicator, connected, _detail = await self._connect(self.viewer)
        self.assertTrue(connected)

        # Act: an event lands on the note's group, shaped exactly as
        # ``NoteVersionEventPublisher`` sends it.
        await get_channel_layer().group_send(
            note_group(self.note.id),
            {
                "type": EVENT_TYPE,
                "data": {
                    "type": NOTE_VERSION_CREATED,
                    "note_id": self.note.id,
                    "version_id": 5001,
                    "parent_version_id": 5000,
                    "created_by": 7,
                    "created_via": "agent",
                    "created_date": "2026-08-12T14:03:22+00:00",
                },
            },
        )

        # Assert: the client receives the data object verbatim.
        self.assertEqual(
            json.loads(await communicator.receive_from()),
            {
                "type": NOTE_VERSION_CREATED,
                "note_id": self.note.id,
                "version_id": 5001,
                "parent_version_id": 5000,
                "created_by": 7,
                "created_via": "agent",
                "created_date": "2026-08-12T14:03:22+00:00",
            },
        )
        await communicator.disconnect()

    async def test_revoked_viewer_is_closed_instead_of_receiving_events(self):
        # Arrange: admitted while permitted, then the permission is revoked
        # (as make_private or remove_permission would).
        communicator, connected, _detail = await self._connect(self.viewer)
        self.assertTrue(connected)
        await database_sync_to_async(
            Permission.objects.filter(user=self.viewer).delete
        )()

        # Act: an event lands on the note's group.
        await get_channel_layer().group_send(
            note_group(self.note.id),
            {
                "type": EVENT_TYPE,
                "data": {"type": NOTE_VERSION_CREATED, "note_id": self.note.id},
            },
        )

        # Assert: access is re-checked per event, so the client is closed,
        # not served.
        output = await communicator.receive_output()
        self.assertEqual(output["type"], "websocket.close")
        self.assertEqual(output["code"], CLOSE_NOT_FOUND)
        await communicator.disconnect()

    async def test_deactivated_subscriber_is_closed_instead_of_receiving_events(self):
        # Arrange
        communicator, connected, _detail = await self._connect(self.viewer)
        self.assertTrue(connected)
        self.viewer.is_active = False
        await self.viewer.asave(update_fields=["is_active"])

        # Act
        await get_channel_layer().group_send(
            note_group(self.note.id),
            {
                "type": EVENT_TYPE,
                "data": {"type": NOTE_VERSION_CREATED, "note_id": self.note.id},
            },
        )

        # Assert
        output = await communicator.receive_output()
        self.assertEqual(output["type"], "websocket.close")
        self.assertEqual(output["code"], CLOSE_UNAUTHENTICATED)
        await communicator.disconnect()

    async def test_creating_a_version_delivers_the_event_end_to_end(self):
        # Arrange
        communicator, connected, _detail = await self._connect(self.viewer)
        self.assertTrue(connected)

        # Act: a version row is committed (autocommit here, so the post-commit
        # publish fires immediately) by the signal-driven default publisher.
        version = await database_sync_to_async(NoteContent.objects.create)(
            note=self.note,
            plain_text="autosave",
            created_by=self.owner,
            created_via=NoteContent.CREATED_VIA_EDITOR,
            parent_version=self.seed_version,
        )

        # Assert
        self.assertEqual(
            json.loads(await communicator.receive_from()),
            {
                "type": NOTE_VERSION_CREATED,
                "note_id": self.note.id,
                "version_id": version.id,
                "parent_version_id": self.seed_version.id,
                "created_by": self.owner.id,
                "created_via": NoteContent.CREATED_VIA_EDITOR,
                "created_date": version.created_date.isoformat(),
            },
        )
        await communicator.disconnect()
