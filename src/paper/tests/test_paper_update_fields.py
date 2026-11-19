from rest_framework.test import APITestCase

from hub.tests.helpers import create_hub
from user.tests.helpers import create_hub_editor, create_random_authenticated_user

from .helpers import create_paper


class PaperUpdateFieldsTests(APITestCase):
    def setUp(self):
        self.paper = create_paper(title="Original title")
        self.url = f"/api/paper/{self.paper.id}/"
        self.moderator = create_random_authenticated_user(
            "paper_update_moderator", moderator=True
        )

    def _patch(self, user, data):
        self.client.force_authenticate(user)
        response = self.client.patch(self.url, data, format="json")
        self.paper.refresh_from_db()
        return response

    def test_moderator_can_update_editable_fields(self):
        # Arrange
        hub = create_hub(name="Editable hub")
        data = {
            "abstract": "New abstract",
            "doi": "10.1000/editable",
            "hubs": [hub.id],
            "paper_publish_date": "2024-02-03",
            "paper_title": "New official title",
            "paper_type": "PRE_REGISTRATION",
            "pdf_license": "cc-by",
            "title": "New title",
        }

        # Act
        response = self._patch(self.moderator, data)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.paper.abstract, "New abstract")
        self.assertEqual(self.paper.doi, "10.1000/editable")
        self.assertEqual(list(self.paper.unified_document.hubs.all()), [hub])
        self.assertEqual(self.paper.paper_publish_date.date().isoformat(), "2024-02-03")
        self.assertEqual(self.paper.paper_title, "New official title")
        self.assertEqual(self.paper.paper_type, "PRE_REGISTRATION")
        self.assertEqual(self.paper.pdf_license, "cc-by")
        self.assertEqual(self.paper.title, "New title")

    def test_update_ignores_other_fields(self):
        # Arrange
        other_user = create_random_authenticated_user("paper_update_other")
        self.paper.pdf_url = "https://example.com/original.pdf"
        self.paper.url = "https://example.com/original"
        self.paper.save()
        data = {
            "citations": 500,
            "external_metadata": {"changed": True},
            "file": "uploads/papers/changed.pdf",
            "is_pdf_removed_by_moderator": True,
            "oa_status": "gold",
            "open_alex_raw_json": {"changed": True},
            "pdf_url": "https://example.com/changed.pdf",
            "title": "Allowed title",
            "uploaded_by": other_user.id,
            "url": "https://example.com/changed",
        }

        # Act
        response = self._patch(self.moderator, data)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.paper.title, "Allowed title")
        self.assertEqual(self.paper.citations, 0)
        self.assertIsNone(self.paper.external_metadata)
        self.assertFalse(self.paper.file)
        self.assertFalse(self.paper.is_pdf_removed_by_moderator)
        self.assertIsNone(self.paper.oa_status)
        self.assertIsNone(self.paper.open_alex_raw_json)
        self.assertEqual(self.paper.pdf_url, "https://example.com/original.pdf")
        self.assertIsNone(self.paper.uploaded_by)
        self.assertEqual(self.paper.url, "https://example.com/original")

    def test_hub_editor_can_update_title_but_not_pdf_license(self):
        # Arrange
        editor, _ = create_hub_editor("paper_update_editor", "Editor hub")

        # Act
        response = self._patch(editor, {"title": "Edited", "pdf_license": "cc-by"})

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.paper.title, "Edited")
        self.assertIsNone(self.paper.pdf_license)
