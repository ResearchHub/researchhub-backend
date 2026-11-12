from django.test import TestCase

from research_ai.models import Artifact
from research_ai.services.agent_persistence import AgentConversationService
from research_ai.services.notebook_chat.artifact_tools import (
    CREATE_ARTIFACT,
    READ_ARTIFACT,
    UPDATE_ARTIFACT,
    ArtifactToolset,
    build_artifacts_notice,
)
from user.tests.helpers import create_random_authenticated_user


class ArtifactToolsetTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("artifact_tools_user")
        conversations = AgentConversationService()
        self.conversation = conversations.create(
            user=self.user, workflow="notebook_chat"
        )
        self.other_conversation = conversations.create(
            user=self.user, workflow="notebook_chat"
        )

    def _call(self, name, args, conversation=None):
        toolset = ArtifactToolset(
            conversation=conversation or self.conversation
        ).as_toolset()
        result, stop = toolset.dispatch(name, args)
        self.assertFalse(stop)
        return result

    def _create(self, **overrides):
        args = {
            "title": "Dose response",
            "kind": "react",
            "content": "export default () => <p>red</p>",
            **overrides,
        }
        return self._call(CREATE_ARTIFACT, args)

    def test_create_returns_a_summary_without_the_content(self):
        # Act
        result = self._create()

        # Assert
        artifact = Artifact.objects.get()
        self.assertEqual(
            result,
            {
                "artifact_id": artifact.id,
                "kind": "react",
                "title": "Dose response",
                "version": 1,
            },
        )
        self.assertEqual(artifact.conversation, self.conversation)

    def test_create_reports_invalid_input_to_the_model(self):
        # Act
        result = self._create(kind="video")

        # Assert
        self.assertIn("kind must be one of", result["error"])

    def test_update_by_edits_and_read_back_each_version(self):
        # Arrange
        artifact_id = self._create()["artifact_id"]

        # Act
        updated = self._call(
            UPDATE_ARTIFACT,
            {
                "artifact_id": artifact_id,
                "edits": [{"old_text": "red", "new_text": "blue"}],
            },
        )
        latest = self._call(READ_ARTIFACT, {"artifact_id": artifact_id})
        first = self._call(READ_ARTIFACT, {"artifact_id": artifact_id, "version": 1})

        # Assert
        self.assertEqual(updated["version"], 2)
        self.assertEqual(latest["content"], "export default () => <p>blue</p>")
        self.assertEqual(latest["latest_version"], 2)
        self.assertEqual(first["content"], "export default () => <p>red</p>")
        self.assertEqual(first["version"], 1)

    def test_update_errors_are_model_readable(self):
        # Arrange
        artifact_id = self._create()["artifact_id"]

        # Act
        missing = self._call(
            UPDATE_ARTIFACT,
            {
                "artifact_id": artifact_id,
                "edits": [{"old_text": "green", "new_text": "blue"}],
            },
        )
        malformed = self._call(
            UPDATE_ARTIFACT, {"artifact_id": artifact_id, "edits": ["red"]}
        )
        no_version = self._call(
            READ_ARTIFACT, {"artifact_id": artifact_id, "version": 5}
        )

        # Assert
        self.assertIn("not found", missing["error"])
        self.assertIn("old_text", malformed["error"])
        self.assertIn("versions are 1 to 1", no_version["error"])

    def test_tools_only_reach_this_chats_artifacts(self):
        # Arrange
        artifact_id = self._create()["artifact_id"]

        # Act
        read = self._call(
            READ_ARTIFACT, {"artifact_id": artifact_id}, self.other_conversation
        )
        update = self._call(
            UPDATE_ARTIFACT,
            {"artifact_id": artifact_id, "content": "x"},
            self.other_conversation,
        )

        # Assert
        self.assertEqual(read, {"error": "no artifact with that id in this chat"})
        self.assertEqual(update, {"error": "no artifact with that id in this chat"})

    def test_notice_lists_artifacts_or_nothing(self):
        # Arrange
        self._create()
        artifact = Artifact.objects.get()

        # Act
        notice = build_artifacts_notice([artifact])

        # Assert
        self.assertIn(
            f'artifact {artifact.id} ("Dose response", react, version 1)', notice
        )
        self.assertIsNone(build_artifacts_notice([]))
