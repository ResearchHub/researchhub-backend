import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from rest_framework.test import APITestCase

from note.models import NoteContent
from note.services.note_content_service import NoteContentService
from note.tests.helpers import create_note
from note.views import note_view
from researchhub_access_group.constants import ADMIN
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubUnifiedDocument


def build_document(href, figure_html):
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "attrs": {"id": "p-1", "onclick": "alert(1)"},
                "content": [
                    {
                        "type": "text",
                        "text": "label",
                        "marks": [{"type": "link", "attrs": {"href": href}}],
                    }
                ],
            },
            {
                "type": "figure",
                "attrs": {"class": "image", "originalContent": figure_html},
            },
        ],
    }


HOSTILE_DOCUMENT = build_document(
    " JaVaScRiPt:alert(1)", "<img src=x onerror=alert(1)>"
)
LEGITIMATE_DOCUMENT = {
    "type": "doc",
    "content": [
        {
            "type": "paragraph",
            "attrs": {"id": "p-1", "textAlign": "left"},
            "content": [
                {
                    "type": "text",
                    "text": "label",
                    "marks": [
                        {"type": "link", "attrs": {"href": "https://example.org"}}
                    ],
                }
            ],
        },
        {
            "type": "figure",
            "attrs": {
                "class": "image",
                "originalContent": '<img src="https://example.org/a.png">',
            },
        },
    ],
}


class NoteRichTextTestCase(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="rich_text@researchhub_test.com",
            password="password",
            email="rich_text@researchhub_test.com",
        )
        self.note, self.seed_version = create_note(self.user, organization=None)
        Permission.objects.create(
            access_type=ADMIN,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=self.note.unified_document_id,
            user=self.user,
        )
        self.client.force_authenticate(self.user)

    def assert_document_is_clean(self, document):
        paragraph, figure = document["content"]
        self.assertEqual(paragraph["attrs"], {"id": "p-1"})
        self.assertEqual(paragraph["content"][0]["marks"], [])
        self.assertEqual(paragraph["content"][0]["text"], "label")
        self.assertEqual(figure["attrs"]["originalContent"], '<img src="x">')


class NoteContentSanitizingTests(NoteRichTextTestCase):
    def _save_version(self, **payload):
        return self.client.post(
            "/api/note_content/", {"note": self.note.id, **payload}, format="json"
        )

    def test_hostile_json_string_is_cleaned_before_storing(self):
        # Act
        response = self._save_version(
            full_json=json.dumps(HOSTILE_DOCUMENT), plain_text="label"
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        version = NoteContent.objects.get(id=response.data["id"])
        self.assertIsInstance(version.json, str)
        self.assert_document_is_clean(json.loads(version.json))

    def test_hostile_json_object_is_cleaned_before_storing(self):
        # Act
        response = self._save_version(full_json=HOSTILE_DOCUMENT)

        # Assert
        self.assertEqual(response.status_code, 200)
        version = NoteContent.objects.get(id=response.data["id"])
        self.assert_document_is_clean(version.json)

    def test_legitimate_json_string_is_stored_byte_for_byte(self):
        # Arrange
        full_json = json.dumps(LEGITIMATE_DOCUMENT, indent=2, sort_keys=True)

        # Act
        response = self._save_version(full_json=full_json)

        # Assert
        self.assertEqual(response.status_code, 200)
        version = NoteContent.objects.get(id=response.data["id"])
        self.assertEqual(version.json, full_json)

    def test_html_only_version_is_cleaned_before_storing(self):
        # Arrange
        stored = []

        def capture(content):
            stored.append(content)
            return ContentFile(content)

        # Act
        with (
            patch.object(note_view, "ContentFile", side_effect=capture),
            patch.object(note_view, "TESTING", False),
        ):
            response = self._save_version(
                full_src="<p onclick=alert(1)>body</p><script>alert(1)</script>"
            )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(stored, [b"<p>body</p>"])
        self.assertEqual(response.data["src"], "<p>body</p>")

    def test_updating_a_version_cleans_its_json(self):
        # Act
        response = self.client.patch(
            f"/api/note_content/{self.seed_version.id}/",
            {"json": HOSTILE_DOCUMENT},
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.seed_version.refresh_from_db()
        self.assert_document_is_clean(self.seed_version.json)

    def test_updating_other_fields_leaves_json_alone(self):
        # Arrange
        NoteContent.objects.filter(id=self.seed_version.id).update(
            json=LEGITIMATE_DOCUMENT
        )

        # Act
        response = self.client.patch(
            f"/api/note_content/{self.seed_version.id}/",
            {"plain_text": "new text"},
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.seed_version.refresh_from_db()
        self.assertEqual(self.seed_version.json, LEGITIMATE_DOCUMENT)
        self.assertEqual(self.seed_version.plain_text, "new text")


class NoteContentServiceSanitizingTests(NoteRichTextTestCase):
    def test_programmatic_versions_are_cleaned(self):
        # Act
        version = NoteContentService().create_version(self.note, HOSTILE_DOCUMENT)

        # Assert
        document = json.loads(version.json)
        figure = next(n for n in document["content"] if n["type"] == "figure")
        link_text = document["content"][0]["content"][0]
        self.assertEqual(figure["attrs"]["originalContent"], '<img src="x">')
        self.assertEqual(link_text["marks"], [])
        self.assertNotIn("onclick", document["content"][0]["attrs"])

    def test_programmatic_legitimate_content_is_kept(self):
        # Act
        version = NoteContentService().create_version(self.note, LEGITIMATE_DOCUMENT)

        # Assert
        document = json.loads(version.json)
        figure = next(n for n in document["content"] if n["type"] == "figure")
        self.assertEqual(
            figure["attrs"]["originalContent"],
            '<img src="https://example.org/a.png">',
        )
        self.assertEqual(
            document["content"][0]["content"][0]["marks"][0]["attrs"]["href"],
            "https://example.org",
        )


class NoteTemplateSanitizingTests(NoteRichTextTestCase):
    def test_template_body_is_cleaned_before_storing(self):
        # Act
        response = self.client.post(
            "/api/note_template/",
            {
                "full_src": '<h1 onclick="alert(1)">Title</h1><img src=x onerror=y>',
                "name": "Template",
            },
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["src"], '<h1>Title</h1><img src="x">')

    def test_legitimate_template_body_is_stored_unchanged(self):
        # Arrange
        body = '<h1 id="a">Title</h1><p style="text-align: center;">Body</p>'

        # Act
        response = self.client.post(
            "/api/note_template/",
            {"full_src": body, "name": "Template"},
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["src"], body)
