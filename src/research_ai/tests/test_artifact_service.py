import unittest

from django.test import TestCase
from rest_framework.test import APITestCase

from research_ai.models import Artifact
from research_ai.services.agent_persistence import AgentConversationService
from research_ai.services.artifact_service import (
    MAX_CONTENT_CHARS,
    ArtifactEdit,
    ArtifactError,
    ArtifactService,
    apply_edits,
)
from user.tests.helpers import create_random_authenticated_user


class ApplyEditsTests(unittest.TestCase):
    def test_applies_edits_in_order_to_the_previous_result(self):
        # Arrange
        edits = [ArtifactEdit("red", "blue"), ArtifactEdit("blue sky", "grey sky")]

        # Act
        result = apply_edits("a red sky", edits)

        # Assert
        self.assertEqual(result, "a grey sky")

    def test_rejects_missing_and_ambiguous_old_text(self):
        # Act / Assert
        with self.assertRaisesRegex(ArtifactError, "not found"):
            apply_edits("abc", [ArtifactEdit("xyz", "q")])
        with self.assertRaisesRegex(ArtifactError, "occurs 2 times"):
            apply_edits("a a", [ArtifactEdit("a", "b")])
        with self.assertRaisesRegex(ArtifactError, "empty"):
            apply_edits("abc", [ArtifactEdit("", "q")])


class ArtifactServiceTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("artifact_service_user")
        self.conversation = AgentConversationService().create(
            user=self.user, workflow="assistant_chat"
        )
        self.service = ArtifactService()

    def test_create_writes_version_one(self):
        # Act
        artifact = self.service.create(
            self.conversation, kind="svg", title="  A  figure ", content="<svg/>"
        )

        # Assert
        self.assertEqual(artifact.title, "A figure")
        self.assertEqual(artifact.latest_version, 1)
        self.assertEqual(self.service.version(artifact).content, "<svg/>")

    def test_create_keeps_language_only_for_code(self):
        # Act
        code = self.service.create(
            self.conversation,
            kind="code",
            title="Fit",
            content="print(1)",
            language="python",
        )
        page = self.service.create(
            self.conversation,
            kind="html",
            title="Page",
            content="<p>hi</p>",
            language="python",
        )

        # Assert
        self.assertEqual(code.language, "python")
        self.assertEqual(page.language, "")

    def test_create_rejects_bad_input(self):
        # Act / Assert
        with self.assertRaisesRegex(ArtifactError, "kind"):
            self.service.create(self.conversation, kind="pdf", title="x", content="x")
        with self.assertRaisesRegex(ArtifactError, "title"):
            self.service.create(self.conversation, kind="svg", title=" ", content="x")
        with self.assertRaisesRegex(ArtifactError, "empty"):
            self.service.create(self.conversation, kind="svg", title="x", content="")
        with self.assertRaisesRegex(ArtifactError, "limit"):
            self.service.create(
                self.conversation,
                kind="svg",
                title="x",
                content="x" * (MAX_CONTENT_CHARS + 1),
            )
        self.assertFalse(Artifact.objects.exists())

    def test_updates_append_versions_and_keep_earlier_ones(self):
        # Arrange
        artifact = self.service.create(
            self.conversation, kind="markdown", title="Doc", content="# One"
        )

        # Act
        self.service.update(artifact, edits=[ArtifactEdit("One", "Two")])
        self.service.update(artifact, content="# Three", title="Renamed")

        # Assert
        artifact.refresh_from_db()
        self.assertEqual(artifact.latest_version, 3)
        self.assertEqual(artifact.title, "Renamed")
        self.assertEqual(self.service.version(artifact, 1).content, "# One")
        self.assertEqual(self.service.version(artifact, 2).content, "# Two")
        self.assertEqual(self.service.version(artifact).content, "# Three")

    def test_a_failed_update_writes_nothing(self):
        # Arrange
        artifact = self.service.create(
            self.conversation, kind="markdown", title="Doc", content="# One"
        )

        # Act / Assert
        with self.assertRaises(ArtifactError):
            self.service.update(artifact, edits=[ArtifactEdit("Missing", "x")])
        with self.assertRaises(ArtifactError):
            self.service.update(artifact, content="x", edits=[])
        with self.assertRaises(ArtifactError):
            self.service.update(artifact)
        artifact.refresh_from_db()
        self.assertEqual(artifact.latest_version, 1)
        self.assertEqual(artifact.versions.count(), 1)

    def test_get_for_user_is_owner_only_and_drops_removed_chats(self):
        # Arrange
        artifact = self.service.create(
            self.conversation, kind="svg", title="x", content="<svg/>"
        )
        other = create_random_authenticated_user("artifact_service_other")

        # Act / Assert
        self.assertEqual(self.service.get_for_user(self.user, artifact.id), artifact)
        self.assertIsNone(self.service.get_for_user(other, artifact.id))
        self.conversation.is_removed = True
        self.conversation.save(update_fields=["is_removed"])
        self.assertIsNone(self.service.get_for_user(self.user, artifact.id))


class ArtifactDetailViewTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("artifact_view_user")
        conversation = AgentConversationService().create(
            user=self.user, workflow="assistant_chat"
        )
        service = ArtifactService()
        self.artifact = service.create(
            conversation, kind="mermaid", title="Flow", content="graph TD; A-->B"
        )
        service.update(self.artifact, content="graph TD; A-->C")

    def test_returns_the_latest_version_or_the_one_asked_for(self):
        # Arrange
        self.client.force_authenticate(self.user)
        url = f"/api/research_ai/artifacts/{self.artifact.id}/"

        # Act
        latest = self.client.get(url)
        first = self.client.get(url, {"version": "1"})

        # Assert
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.data["kind"], "mermaid")
        self.assertEqual(latest.data["latest_version"], 2)
        self.assertEqual(latest.data["version"]["number"], 2)
        self.assertEqual(latest.data["version"]["content"], "graph TD; A-->C")
        self.assertEqual(first.data["version"]["content"], "graph TD; A-->B")

    def test_is_a_404_for_other_users_and_unknown_versions(self):
        # Arrange
        url = f"/api/research_ai/artifacts/{self.artifact.id}/"
        other = create_random_authenticated_user("artifact_view_other")

        # Act
        self.client.force_authenticate(other)
        foreign = self.client.get(url)
        self.client.force_authenticate(self.user)
        missing = self.client.get(url, {"version": "9"})
        malformed = self.client.get(url, {"version": "x"})

        # Assert
        self.assertEqual(foreign.status_code, 404)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(malformed.status_code, 404)
