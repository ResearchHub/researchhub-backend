from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from note.tests.helpers import create_note
from research_ai.models import AgentFile, NoteCoverLogo
from research_ai.services.agent_persistence import AgentConversationService
from research_ai.services.notebook_chat.cover_logo_tools import CoverLogoToolset
from research_ai.tests.agent_files.helpers import make_file
from researchhub_access_group.constants import ADMIN, VIEWER
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubUnifiedDocument
from user.tests.helpers import create_random_authenticated_user


class SetCoverLogoToolTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("cover_logo_user")
        self.note, _ = create_note(self.user, organization=None)
        self.permission = Permission.objects.create(
            access_type=ADMIN,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=self.note.unified_document_id,
            user=self.user,
        )
        conversations = AgentConversationService()
        self.conversation = conversations.create(
            user=self.user, workflow="notebook_chat"
        )
        self.message = conversations.add_human_message(
            self.conversation, "Here is our logo"
        )
        self.logo = make_file(
            self.user,
            message=self.message,
            filename="logo.png",
            content_type="image/png",
            text="",
        )

    def _set(self, args, conversation=None):
        toolset = CoverLogoToolset(
            note=self.note,
            conversation=conversation or self.conversation,
            user=self.user,
        ).as_toolset()
        result, stop = toolset.dispatch(CoverLogoToolset.SET_COVER_LOGO, args)
        self.assertFalse(stop)
        return result

    def test_records_an_attached_image_as_the_cover_logo(self):
        # Act
        result = self._set({"attachment_id": self.logo.id})

        # Assert
        self.assertEqual(
            result,
            {
                "note_id": self.note.id,
                "cover_logo": {"attachment_id": self.logo.id, "filename": "logo.png"},
                "saved": True,
            },
        )
        self.assertEqual(NoteCoverLogo.objects.get(note=self.note).file, self.logo)

    def test_replaces_and_clears_the_cover_logo(self):
        # Arrange
        newer = make_file(
            self.user,
            message=self.message,
            filename="logo-v2.png",
            content_type="image/png",
            text="",
        )
        self._set({"attachment_id": self.logo.id})

        # Act
        self._set({"attachment_id": newer.id})
        replaced = NoteCoverLogo.objects.get(note=self.note).file
        cleared = self._set({"attachment_id": None})

        # Assert
        self.assertEqual(replaced, newer)
        self.assertIsNone(cleared["cover_logo"])
        self.assertFalse(NoteCoverLogo.objects.filter(note=self.note).exists())

    def test_refuses_an_attachment_that_is_not_an_image(self):
        # Arrange
        document = make_file(self.user, message=self.message)

        # Act
        result = self._set({"attachment_id": document.id})

        # Assert
        self.assertEqual(
            result, {"error": "the cover logo must be an image attachment"}
        )
        self.assertFalse(NoteCoverLogo.objects.exists())

    def test_refuses_an_attachment_from_another_chat(self):
        # Arrange
        other_conversation = AgentConversationService().create(
            user=self.user, workflow="notebook_chat"
        )

        # Act
        result = self._set(
            {"attachment_id": self.logo.id}, conversation=other_conversation
        )

        # Assert
        self.assertEqual(
            result, {"error": "no uploaded attachment with that id in this chat"}
        )

    def test_refuses_an_attachment_still_processing(self):
        # Arrange
        AgentFile.objects.filter(id=self.logo.id).update(
            status=AgentFile.Status.PROCESSING
        )

        # Act
        result = self._set({"attachment_id": self.logo.id})

        # Assert
        self.assertIn("error", result)
        self.assertFalse(NoteCoverLogo.objects.exists())

    def test_a_viewer_cannot_set_the_cover_logo(self):
        # Arrange
        self.permission.access_type = VIEWER
        self.permission.save(update_fields=["access_type"])

        # Act
        result = self._set({"attachment_id": self.logo.id})

        # Assert
        self.assertEqual(
            result, {"error": "no permission to change this note's cover logo"}
        )

    def test_attachment_id_is_required(self):
        # Act
        result = self._set({})

        # Assert
        self.assertEqual(
            result,
            {"error": "attachment_id is required; pass null to remove the logo"},
        )
