from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from paper.serializers import DynamicPaperSerializer
from paper.utils import (
    convert_journal_url_to_pdf_url,
    convert_pdf_url_to_journal_url,
    pdf_copyright_allows_display,
)
from utils.test_helpers import IntegrationTestHelper, TestHelper


class PaperIntegrationTests(TestCase, TestHelper, IntegrationTestHelper):
    base_url = "/api/paper/"

    def test_get_base_route(self):
        response = self.get_get_response(self.base_url)
        self.assertEqual(response.status_code, 200)

    def submit_paper_form(self):
        client = self.get_default_authenticated_client()
        url = self.base_url
        form_data = self.build_paper_form()
        response = client.post(url, form_data)
        return response

    def build_paper_form(self):
        file = SimpleUploadedFile("../config/paper.pdf", b"file_content")
        hub = self.create_hub("Film")
        hub_2 = self.create_hub("Comedy")
        university = self.create_university(name="Charleston")
        author = self.create_author_without_user(
            university, first_name="Donald", last_name="Duck"
        )

        form = {
            "title": "The Simple Paper",
            "paper_publish_date": self.paper_publish_date,
            "file": file,
            "hubs": [hub.id, hub_2.id],
            "authors": [author.id],
        }
        return form


class JournalPdfTests(TestCase):
    journal_test_urls = [
        "https://arxiv.org/abs/2007.10529",
        "https://jpet.aspetjournals.org/content/368/1/59",
        "https://www.biorxiv.org/content/10.1101/2020.04.14.040808v1",
        "https://www.jneurosci.org/content/29/13/3974",
        "https://www.thelancet.com/journals/journal_id/article/PIIS2215-0366(20)30308-4/fulltext",
        "https://www.nature.com/articles/srep42765",
        "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0198090",
        "https://www.pnas.org/content/102/4/1193",
        "https://advances.sciencemag.org/content/1/6/e1500251",
        "https://onlinelibrary.wiley.com/doi/full/10.1111/jvim.15646",
        "https://academic.oup.com/nar/article/46/W1/W180/5033528",
    ]

    pdf_test_urls = [
        "https://arxiv.org/pdf/2007.10529.pdf",
        "https://jpet.aspetjournals.org/content/jpet/368/1/59.full.pdf",
        "https://www.biorxiv.org/content/10.1101/2020.04.14.040808v1.full.pdf",
        "https://www.jneurosci.org/content/jneuro/29/13/3974.full.pdf",
        "https://www.thelancet.com/action/showPdf?pii=S2215-0366(20)30308-4",
        "https://www.nature.com/articles/srep42765.pdf",
        "https://journals.plos.org/plosone/article/file?id=10.1371/journal.pone.0198090&type=printable",
        "https://www.pnas.org/content/pnas/102/4/1193.full.pdf",
        "https://advances.sciencemag.org/content/advances/1/6/e1500251.full.pdf",
        "https://onlinelibrary.wiley.com/doi/pdfdirect/10.1111/jvim.15646?download=true",
        "https://academic.oup.com/nar/article-pdf/46/W1/W180/25110691/gky509.pdf",
    ]

    def test_journal_to_pdf(self):
        for i, url in enumerate(self.journal_test_urls):
            pdf_url, exists = convert_journal_url_to_pdf_url(url)
            if exists:
                self.assertEqual(pdf_url, self.pdf_test_urls[i])

    def test_pdf_to_journal(self):
        for i, url in enumerate(self.pdf_test_urls):
            journal_url, exists = convert_pdf_url_to_journal_url(url)
            if exists:
                self.assertEqual(journal_url, self.journal_test_urls[i])


class PaperPatchTest(TestCase, TestHelper, IntegrationTestHelper):
    base_url = "/api/paper/"

    def create_paper(self, doi="1.1.1.2"):
        original_paper = self.create_paper_without_authors()
        original_paper.raw_authors = [{"first_name": "First", "last_name": "Last"}]
        original_paper.save()
        return original_paper

    def test_patch_paper(self):
        paper = self.create_paper()
        updated_title = "Updated Title"
        form = {
            "title": updated_title,
        }
        client = self.get_default_authenticated_client()
        url = f"{self.base_url}{paper.id}/?make_public=true"
        response = client.patch(url, form, content_type="application/json")
        data = response.data
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["title"], updated_title)
        self.assertEqual(
            data["raw_authors"], [{"first_name": "First", "last_name": "Last"}]
        )


class PaperPropertiesTest(TestCase, TestHelper):
    def test_low_cited_paper_does_not_have_highly_cited_property(self):
        paper = self.create_paper_without_authors()
        paper.open_alex_raw_json = {
            "id": "https://openalex.org/W4286008317",
            "cited_by_count": 10,
            "cited_by_percentile_year": {"max": 80, "min": 70},
        }
        paper.save()
        paper.refresh_from_db()
        self.assertFalse(paper.is_highly_cited)

    def test_highly_cited_paper_does_have_highly_cited_property(self):
        paper = self.create_paper_without_authors()
        paper.open_alex_raw_json = {
            "id": "https://openalex.org/W4286008317",
            "cited_by_count": 100,
            "cited_by_percentile_year": {"max": 80, "min": 70},
        }
        paper.save()
        paper.refresh_from_db()
        self.assertTrue(paper.is_highly_cited)


class PaperCopyrightTest(TestCase, TestHelper):
    def setUp(self):
        mock_file = SimpleUploadedFile(
            "test.pdf",
            b"These are the contents of the pdf file.",
            content_type="application/pdf",
        )

        self.paper = self.create_paper_without_authors()
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
