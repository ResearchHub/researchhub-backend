import json

from asgiref.testing import ApplicationCommunicator
from channels.layers import get_channel_layer
from channels.routing import URLRouter
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.contenttypes.models import ContentType
from django.test import TransactionTestCase

import research_ai.routing
from note.tests.helpers import create_note
from research_ai.consumers import (
    CLOSE_FORBIDDEN,
    CLOSE_NOT_FOUND,
    CLOSE_UNAUTHENTICATED,
)
from research_ai.services.notebook_chat import NotebookChatService
from research_ai.services.notebook_chat.events import EVENT_TYPE, conversation_group
from researchhub_access_group.constants import ADMIN
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubUnifiedDocument

application = URLRouter(research_ai.routing.websocket_urlpatterns)


class NotebookChatConsumerTests(TransactionTestCase):
    """Admission mirrors the REST contract; events are forwarded verbatim.

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
        self.user = user_model.objects.create_user(
            username="owner@researchhub_test.com",
            password="password",
            email="owner@researchhub_test.com",
        )
        self.other_user = user_model.objects.create_user(
            username="other@researchhub_test.com",
            password="password",
            email="other@researchhub_test.com",
        )

        self.note = create_note(self.user, organization=None)[0]
        self._grant_note_access(self.user, self.note)
        self._grant_note_access(self.other_user, self.note)
        service = NotebookChatService()
        self.conversation = service.create_conversation(self.note, self.user)
        self.other_conversation = service.create_conversation(
            self.note, self.other_user
        )

        # A second note the owner can view, with no chats on it.
        self.other_note = create_note(self.user, organization=None)[0]
        self._grant_note_access(self.user, self.other_note)

        # A note the owner has no access to at all.
        self.hidden_note = create_note(self.other_user, organization=None)[0]

    def _grant_note_access(self, user, note):
        Permission.objects.create(
            access_type=ADMIN,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=note.unified_document.id,
            user=user,
        )

    async def _connect(self, user, *, note_id=None, conversation_id=None):
        note_id = self.note.id if note_id is None else note_id
        conversation_id = (
            self.conversation.id if conversation_id is None else conversation_id
        )
        communicator = ApplicationCommunicator(
            application,
            {
                "type": "websocket",
                "path": f"/ws/notebook/notes/{note_id}/chats/{conversation_id}/",
                "user": user,
            },
        )
        await communicator.send_input({"type": "websocket.connect"})
        return communicator, await communicator.receive_output()

    async def test_anonymous_connection_is_rejected(self):
        # Act
        _communicator, response = await self._connect(AnonymousUser())

        # Assert
        self.assertEqual(response["type"], "websocket.close")
        self.assertEqual(response["code"], CLOSE_UNAUTHENTICATED)

    async def test_deactivated_account_is_rejected(self):
        # Arrange: the account is disabled but its token still resolves, the
        # state the auth middleware hands over for a lingering token.
        self.user.is_active = False
        await self.user.asave(update_fields=["is_active"])

        # Act
        _communicator, response = await self._connect(self.user)

        # Assert: deactivation revokes the socket like it revokes the REST API.
        self.assertEqual(response["type"], "websocket.close")
        self.assertEqual(response["code"], CLOSE_UNAUTHENTICATED)

    async def test_suspended_user_is_rejected(self):
        # Arrange
        self.user.is_suspended = True
        await self.user.asave(update_fields=["is_suspended"])

        # Act
        _communicator, response = await self._connect(self.user)

        # Assert
        self.assertEqual(response["type"], "websocket.close")
        self.assertEqual(response["code"], CLOSE_FORBIDDEN)

    async def test_someone_elses_conversation_reads_as_not_found(self):
        # Arrange: a moderator who can view the note but does not own the
        # chat; like the REST API, ownership failures leak nothing.
        self.other_user.moderator = True
        await self.other_user.asave(update_fields=["moderator"])

        # Act
        _communicator, response = await self._connect(self.other_user)

        # Assert
        self.assertEqual(response["type"], "websocket.close")
        self.assertEqual(response["code"], CLOSE_NOT_FOUND)

    async def test_an_invisible_note_reads_as_not_found(self):
        # Act: the note exists but the user cannot view it; the close code
        # matches a missing note's, so nothing about it leaks.
        _communicator, response = await self._connect(
            self.user, note_id=self.hidden_note.id
        )

        # Assert
        self.assertEqual(response["type"], "websocket.close")
        self.assertEqual(response["code"], CLOSE_NOT_FOUND)

    async def test_conversation_on_another_note_reads_as_not_found(self):
        # Act: a note the owner can view, but the chat lives on a different
        # one -- the (note, conversation) pair must not resolve.
        _communicator, response = await self._connect(
            self.user, note_id=self.other_note.id
        )

        # Assert
        self.assertEqual(response["type"], "websocket.close")
        self.assertEqual(response["code"], CLOSE_NOT_FOUND)

    async def test_owner_connects_and_receives_published_events(self):
        # Arrange
        communicator, response = await self._connect(self.user)
        self.assertEqual(response["type"], "websocket.accept")
        self.assertEqual(response["subprotocol"], "Token")

        # Act: an event lands on the conversation's group, shaped exactly as
        # ``ConversationEventPublisher`` sends it.
        await get_channel_layer().group_send(
            conversation_group(self.conversation.id),
            {
                "type": EVENT_TYPE,
                "data": {
                    "conversation_id": self.conversation.id,
                    "execution_id": 5,
                    "kind": "turn_progress",
                },
            },
        )

        # Assert: the client receives the data object verbatim.
        output = await communicator.receive_output()
        self.assertEqual(output["type"], "websocket.send")
        self.assertEqual(
            json.loads(output["text"]),
            {
                "conversation_id": self.conversation.id,
                "execution_id": 5,
                "kind": "turn_progress",
            },
        )
        await communicator.send_input({"type": "websocket.disconnect", "code": 1000})
        await communicator.wait()
