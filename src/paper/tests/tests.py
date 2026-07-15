from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APITestCase

from paper.serializers import DynamicPaperSerializer
from paper.utils import pdf_copyright_allows_display
from user.tests.helpers import create_random_authenticated_user

from .helpers import create_paper as create_test_paper


class PaperIntegrationTests(APITestCase):
    def test_get_base_route(self):
        response = self.client.get("/api/paper/")
        self.assertEqual(response.status_code, 200)


class PaperPatchTest(APITestCase):
    base_url = "/api/paper/"

    def create_paper(self, doi="1.1.1.2"):
        original_paper = create_test_paper()
        original_paper.raw_authors = [{"first_name": "First", "last_name": "Last"}]
        original_paper.save()
        return original_paper

    def test_patch_paper(self):
        paper = self.create_paper()
        updated_title = "Updated Title"
        form = {
            "title": updated_title,
        }
        user = create_random_authenticated_user("paper_patch")
        url = f"{self.base_url}{paper.id}/?make_public=true"
        self.client.force_authenticate(user)
        response = self.client.patch(url, form, format="json")
        data = response.data
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["title"], updated_title)
        self.assertEqual(
            data["raw_authors"], [{"first_name": "First", "last_name": "Last"}]
        )


class PaperCopyrightTest(TestCase):
    def setUp(self):
        mock_file = SimpleUploadedFile(
            "test.pdf",
            b"These are the contents of the pdf file.",
            content_type="application/pdf",
        )

        self.paper = create_test_paper()
        self.paper.pdf_url = "https://arxiv.org/pdf/1706.03762.pdf"
        self.paper.file = mock_file
        self.paper.save()

    # Unit-test util function

    def test_dont_display_pdf_if_oa_closed(self):
        self.paper.oa_status = "closed"
        self.paper.save()
        self.assertFalse(pdf_copyright_allows_display(self.paper))

    def test_display_pdf_if_oa_gold(self):
        self.paper.oa_status = "gold"
        self.paper.save()
        self.assertTrue(pdf_copyright_allows_display(self.paper))

    def test_dont_display_pdf_if_license_publisher_specific(self):
        self.paper.pdf_license = "publisher-specific, author manuscript"  # from https://api.openalex.org/works?group_by=primary_location.license:include_unknown
        self.paper.save()
        self.assertFalse(pdf_copyright_allows_display(self.paper))

    def test_display_pdf_if_license_cc_by(self):
        self.paper.pdf_license = "cc-by"
        self.paper.save()
        self.assertTrue(pdf_copyright_allows_display(self.paper))

    def test_dont_display_pdf_if_removed_by_mod(self):
        self.paper.is_pdf_removed_by_moderator = True
        self.paper.save()
        self.assertFalse(pdf_copyright_allows_display(self.paper))

    # Unit-test serializers

    def test_paper_serializer_hides_file_if_pdf_copyrighted(self):
        self.paper.oa_status = "closed"
        self.paper.save()

        serializer = DynamicPaperSerializer(self.paper)
        self.assertIsNone(serializer.data["file"])
        self.assertIsNone(serializer.data["pdf_url"])

    def test_paper_serializer_shows_file_if_pdf_open(self):
        self.paper.oa_status = "gold"
        self.paper.save()

        serializer = DynamicPaperSerializer(self.paper)
        self.assertIsNotNone(serializer.data["file"])
        self.assertIsNotNone(serializer.data["pdf_url"])
