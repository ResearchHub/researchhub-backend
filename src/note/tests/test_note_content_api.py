import json

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APITestCase

from note.models import NoteContent
from note.tests.helpers import create_note
from researchhub_access_group.constants import ADMIN, VIEWER
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubUnifiedDocument

TIPTAP_DOC_JSON = json.dumps(
    {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "hello"}]}
        ],
    }
)


class NoteContentApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.author = user_model.objects.create_user(
            username="author@researchhub_test.com",
            password="password",
            email="author@researchhub_test.com",
        )
        self.viewer = user_model.objects.create_user(
            username="viewer@researchhub_test.com",
            password="password",
            email="viewer@researchhub_test.com",
        )
        self.outsider = user_model.objects.create_user(
            username="outsider@researchhub_test.com",
            password="password",
            email="outsider@researchhub_test.com",
        )

        self.note, self.seed_version = create_note(self.author, organization=None)
        doc_ct = ContentType.objects.get_for_model(ResearchhubUnifiedDocument)
        Permission.objects.create(
            access_type=ADMIN,
            content_type=doc_ct,
            object_id=self.note.unified_document.id,
            user=self.author,
        )
        Permission.objects.create(
            access_type=VIEWER,
            content_type=doc_ct,
            object_id=self.note.unified_document.id,
            user=self.viewer,
        )

    def _post_version(self, **extra):
        payload = {
            "note": self.note.id,
            "full_json": TIPTAP_DOC_JSON,
            "plain_text": "hello",
            **extra,
        }
        return self.client.post("/api/note_content/", payload)

    def test_create_returns_the_new_version_id_and_attribution(self):
        # Arrange
        self.client.force_authenticate(self.author)

        # Act
        response = self._post_version()

        # Assert: the client uses the returned id to recognize its own save
        # in the note_version_created event stream.
        self.assertEqual(response.status_code, 200)
        self.note.refresh_from_db()
        self.assertEqual(response.data["id"], self.note.latest_version_id)
        self.assertEqual(response.data["created_via"], NoteContent.CREATED_VIA_EDITOR)
        self.assertEqual(response.data["created_by"], self.author.id)
        self.assertIsNone(response.data["parent_version"])

    def test_create_records_the_reported_parent_version(self):
        # Arrange
        self.client.force_authenticate(self.author)

        # Act
        response = self._post_version(parent_version=self.seed_version.id)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["parent_version"], self.seed_version.id)

    def test_create_rejects_a_parent_version_of_another_note(self):
        # Arrange
        _other_note, other_version = create_note(self.author, organization=None)
        self.client.force_authenticate(self.author)

        # Act
        response = self._post_version(parent_version=other_version.id)

        # Assert
        self.assertEqual(response.status_code, 400)

    def test_create_rejects_a_malformed_parent_version(self):
        # Arrange
        self.client.force_authenticate(self.author)

        # Act
        response = self._post_version(parent_version="not-an-id")

        # Assert
        self.assertEqual(response.status_code, 400)

    def test_create_denied_without_editing_permission(self):
        # Arrange: read access only.
        self.client.force_authenticate(self.viewer)

        # Act
        response = self._post_version()

        # Assert
        self.assertEqual(response.status_code, 403)

    def test_retrieve_allows_a_read_only_viewer(self):
        # Arrange: fetching one exact version (e.g. the agent's edit when
        # newer autosaves exist) needs only the note's read permission.
        self.client.force_authenticate(self.viewer)

        # Act
        response = self.client.get(f"/api/note_content/{self.seed_version.id}/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], self.seed_version.id)
        self.assertEqual(response.data["plain_text"], "some text")

    def test_update_cannot_forge_attribution_or_lineage(self):
        # Arrange: an editor of the note tries to rewrite server-owned fields.
        other_note, other_version = create_note(self.author, organization=None)
        version = NoteContent.objects.create(
            note=self.note,
            plain_text="v2",
            created_by=self.author,
            created_via=NoteContent.CREATED_VIA_EDITOR,
            parent_version=self.seed_version,
        )
        self.client.force_authenticate(self.author)

        # Act
        response = self.client.patch(
            f"/api/note_content/{version.id}/",
            {
                "created_by": self.outsider.id,
                "created_via": NoteContent.CREATED_VIA_AGENT,
                "parent_version": other_version.id,
                "note": other_note.id,
            },
        )

        # Assert: the read-only fields are ignored and the row is unchanged.
        self.assertEqual(response.status_code, 200)
        version.refresh_from_db()
        self.assertEqual(version.created_by_id, self.author.id)
        self.assertEqual(version.created_via, NoteContent.CREATED_VIA_EDITOR)
        self.assertEqual(version.parent_version_id, self.seed_version.id)
        self.assertEqual(version.note_id, self.note.id)

    def test_retrieve_denied_for_a_soft_deleted_note(self):
        # Arrange: deleting a note leaves permissions intact, so versions
        # must read as missing like the note detail does.
        self.note.unified_document.is_removed = True
        self.note.unified_document.save(update_fields=["is_removed"])
        self.client.force_authenticate(self.viewer)

        # Act
        response = self.client.get(f"/api/note_content/{self.seed_version.id}/")

        # Assert
        self.assertEqual(response.status_code, 404)

    def test_retrieve_denied_without_read_access(self):
        # Arrange
        self.client.force_authenticate(self.outsider)

        # Act
        response = self.client.get(f"/api/note_content/{self.seed_version.id}/")

        # Assert
        self.assertEqual(response.status_code, 403)
