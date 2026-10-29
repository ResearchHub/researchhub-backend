from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from paper.models import Paper, PaperVersion
from paper.related_models.paper_model import JOURNAL_PAPER_IDS
from paper.tests.helpers import add_to_journal, create_paper
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import (
    create_hub_editor,
    create_random_authenticated_user,
)


class PaperDOITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        # Only moderators and hub editors may import papers by DOI
        self.user = create_random_authenticated_user("doi_moderator", moderator=True)
        self.client.force_authenticate(user=self.user)

    def test_retrieve_by_doi_invalid_doi(self):
        """Test that invalid DOIs return a 400 error"""
        url = reverse("paper-retrieve-by-doi")

        # Test with no DOI
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "DOI is required")

        # Test with invalid DOI format
        response = self.client.get(url + "?doi=invalid_doi")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Invalid DOI format")

    def test_retrieve_by_doi_existing_paper(self):
        """Test retrieving an existing paper by DOI"""
        test_doi = "10.1234/test.123"
        paper = create_paper()
        paper.doi = test_doi
        paper.save()
        url = reverse("paper-retrieve-by-doi")

        # Test with bare DOI
        response = self.client.get(url + f"?doi={test_doi}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["doi"], test_doi)
        self.assertEqual(response.data["id"], paper.id)

        # Test with normalized DOI
        normalized_doi = f"https://doi.org/{test_doi}"
        response = self.client.get(url + f"?doi={normalized_doi}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["doi"], test_doi)
        self.assertEqual(response.data["id"], paper.id)

    @patch("utils.openalex.OpenAlex.get_authors")
    @patch("utils.openalex.OpenAlex.get_work_by_doi")
    def test_retrieve_by_doi_new_paper_from_openalex(
        self, mock_get_work, mock_get_authors
    ):
        """Test creating a new paper from OpenAlex when DOI not found"""
        test_doi = "10.1234/new.123"
        mock_work = {
            "id": "W123",
            "doi": test_doi,
            "title": "Test Paper",
            "abstract": "Test abstract",
            "authorships": [
                {
                    "author": {
                        "id": "https://openalex.org/A123",
                        "display_name": "Test Author",
                    },
                    "author_position": "first",
                    "is_corresponding": True,
                    "institutions": [],
                }
            ],
            "publication_year": 2023,
        }
        mock_get_work.return_value = mock_work

        mock_author = {
            "id": "https://openalex.org/A123",
            "display_name": "Test Author",
            "orcid": None,
            "summary_stats": {
                "h_index": 10,
                "i10_index": 5,
                "2yr_mean_citedness": 2.0,
            },
            "works_count": 20,
            "cited_by_count": 100,
        }
        mock_get_authors.return_value = ([mock_author], None)

        url = reverse("paper-retrieve-by-doi")
        response = self.client.get(url + f"?doi={test_doi}")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["doi"], test_doi)
        self.assertEqual(response.data["paper_title"], "Test Paper")

        # Verify paper was created in database
        self.assertTrue(Paper.objects.filter(doi=test_doi).exists())

    @patch("utils.openalex.OpenAlex.get_authors")
    @patch("utils.openalex.OpenAlex.get_work_by_doi")
    def test_retrieve_by_doi_secondary_location_doi(
        self, mock_get_work, mock_get_authors
    ):
        """Test a DOI that OpenAlex files under a work with another primary DOI"""
        # Arrange
        requested_doi = "10.5555/secondary.123"
        primary_doi = "10.5555/primary.123"
        mock_get_work.return_value = {
            "id": "https://openalex.org/W123",
            "doi": f"https://doi.org/{primary_doi}",
            "title": "Merged Paper",
            "authorships": [],
            "publication_year": 2025,
        }
        mock_get_authors.return_value = ([], None)
        url = reverse("paper-retrieve-by-doi")

        # Act
        first_response = self.client.get(url + f"?doi={requested_doi}")
        second_response = self.client.get(url + f"?doi={requested_doi}")

        # Assert
        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(first_response.data["doi"], primary_doi)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.data["id"], first_response.data["id"])
        self.assertEqual(
            Paper.objects.filter(openalex_id="https://openalex.org/W123").count(), 1
        )

    @patch("utils.openalex.OpenAlex.get_work_by_doi")
    @patch(
        "paper.ingestion.clients.registrations.osf.OSFRegistrationClient.fetch_registration"
    )
    def test_retrieve_by_doi_osf_registration(self, mock_fetch, mock_get_work):
        """Test that OSF registration DOIs are imported from OSF, not OpenAlex"""
        # Arrange
        mock_fetch.return_value = {
            "id": "wzubg",
            "attributes": {
                "title": "Research plan title",
                "description": "Research plan abstract",
                "date_registered": "2026-08-31T21:21:16.905334",
                "withdrawn": False,
                "registration_responses": {"340-18": "Outcomes report title"},
            },
            "provider": "Lifecycle Journal",
            "url": "https://osf.io/wzubg/",
            "contributors": [],
            "response_labels": {"340-18": "Short Title:"},
        }
        url = reverse("paper-retrieve-by-doi")

        # Act
        response = self.client.get(url + "?doi=10.17605/OSF.IO/WZUBG")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["doi"], "10.17605/osf.io/wzubg")
        self.assertEqual(response.data["paper_title"], "Outcomes report title")
        mock_fetch.assert_called_once_with("wzubg")
        mock_get_work.assert_not_called()

    @patch("utils.openalex.OpenAlex.get_work_by_doi")
    @patch(
        "paper.ingestion.clients.registrations.osf.OSFRegistrationClient.fetch_registration"
    )
    def test_retrieve_by_doi_does_not_import_for_other_users(
        self, mock_fetch, mock_get_work
    ):
        """Test that only moderators and hub editors can import missing papers"""
        # Arrange
        url = reverse("paper-retrieve-by-doi")
        regular_user = create_random_authenticated_user("doi_regular_user")

        for user in [None, regular_user]:
            self.client.force_authenticate(user)
            for doi in ["10.1234/new.123", "10.17605/OSF.IO/WZUBG"]:
                # Act
                response = self.client.get(url + f"?doi={doi}")

                # Assert
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
                self.assertEqual(response.data["error"], "Paper not found")

        mock_fetch.assert_not_called()
        mock_get_work.assert_not_called()
        self.assertFalse(Paper.objects.exists())

    @patch("utils.openalex.OpenAlex.get_work_by_doi")
    def test_retrieve_by_doi_hub_editor_can_import(self, mock_get_work):
        """Test that hub editors can import missing papers"""
        # Arrange
        editor, _ = create_hub_editor("doi_editor", "DOI Hub")
        self.client.force_authenticate(editor)
        mock_get_work.return_value = None
        url = reverse("paper-retrieve-by-doi")

        # Act
        response = self.client.get(url + "?doi=10.1234/new.123")

        # Assert
        self.assertEqual(response.data["error"], "Work not found")
        mock_get_work.assert_called_once_with("10.1234/new.123")

    def test_retrieve_by_doi_existing_paper_for_regular_user(self):
        """Test that any user can still look up a paper that already exists"""
        # Arrange
        paper = create_paper()
        paper.doi = "10.1234/existing.123"
        paper.save()
        self.client.force_authenticate(None)
        url = reverse("paper-retrieve-by-doi")

        # Act
        response = self.client.get(url + "?doi=10.1234/existing.123")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], paper.id)

    @patch("utils.openalex.OpenAlex.get_work_by_doi")
    def test_retrieve_by_doi_openalex_not_found(self, mock_get_work):
        """Test handling when paper not found in OpenAlex"""
        test_doi = "10.1234/notfound.123"
        mock_get_work.return_value = None

        url = reverse("paper-retrieve-by-doi")
        response = self.client.get(url + f"?doi={test_doi}")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "Work not found")

    def test_retrieve_by_doi_with_doi_org_prefix(self):
        """Test that DOIs with doi.org prefix are handled correctly"""
        test_doi = "10.1234/test.456"
        paper = create_paper()
        paper.doi = test_doi  # Set the DOI
        paper.save()
        url = reverse("paper-retrieve-by-doi")

        # Test with https://doi.org/ prefix
        response = self.client.get(url + f"?doi=https://doi.org/{test_doi}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["doi"], test_doi)
        self.assertEqual(response.data["id"], paper.id)

        # Test with doi.org/ prefix
        response = self.client.get(url + f"?doi=doi.org/{test_doi}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["doi"], test_doi)
        self.assertEqual(response.data["id"], paper.id)

    def test_retrieve_by_doi_with_https_variations(self):
        """Test that DOIs with various https://doi.org formats are handled correctly"""
        test_doi = "10.1234/test.789"
        paper = create_paper()
        paper.doi = test_doi
        paper.save()
        url = reverse("paper-retrieve-by-doi")

        # Test variations of https://doi.org
        variations = [
            f"https://doi.org/{test_doi}",
            f"https://doi.org/{test_doi}/",  # With trailing slash
            f"https://www.doi.org/{test_doi}",  # With www
            f"HTTPS://DOI.ORG/{test_doi}",  # Different case
            f"https://doi.org/doi/{test_doi}",  # With extra doi path
        ]

        for doi_url in variations:
            response = self.client.get(url + f"?doi={doi_url}")
            self.assertEqual(
                response.status_code, status.HTTP_200_OK, f"Failed for DOI: {doi_url}"
            )
            self.assertEqual(response.data["doi"], test_doi)
            self.assertEqual(response.data["id"], paper.id)


class PaperPendingVisibilityTests(TestCase):
    """Papers awaiting moderation are not publicly retrievable by direct link."""

    def setUp(self):
        self.client = APIClient()
        self.uploader = create_random_authenticated_user("paper_uploader")
        self.pending_paper = add_to_journal(
            create_paper(title="Pending paper", uploaded_by=self.uploader)
        )
        self.pending_paper.unified_document.status = ResearchhubUnifiedDocument.PENDING
        self.pending_paper.unified_document.save(update_fields=["status"])
        self.detail_url = reverse("paper-detail", args=[self.pending_paper.id])

    def test_anonymous_cannot_retrieve_pending_paper(self):
        self.client.force_authenticate(None)
        self.assertEqual(
            self.client.get(self.detail_url).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_outsider_cannot_retrieve_pending_paper(self):
        outsider = create_random_authenticated_user("paper_outsider")
        self.client.force_authenticate(outsider)
        self.assertEqual(
            self.client.get(self.detail_url).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_uploader_can_retrieve_pending_paper(self):
        self.client.force_authenticate(self.uploader)
        self.assertEqual(
            self.client.get(self.detail_url).status_code, status.HTTP_200_OK
        )

    def test_moderator_can_retrieve_pending_paper(self):
        moderator = create_random_authenticated_user("paper_mod", moderator=True)
        self.client.force_authenticate(moderator)
        self.assertEqual(
            self.client.get(self.detail_url).status_code, status.HTTP_200_OK
        )


class PaperJournalOnlyRetrieveTests(TestCase):
    """Only the journal's papers have pages; every other paper is not found."""

    def setUp(self):
        self.client = APIClient()
        self.journal_paper = add_to_journal(create_paper(title="Journal paper"))
        self.listed_paper = Paper.objects.create(
            id=min(JOURNAL_PAPER_IDS),
            title="Listed paper",
            unified_document=ResearchhubUnifiedDocument.objects.create(
                document_type="PAPER"
            ),
        )
        self.other_paper = create_paper(title="Other paper")

    def _status(self, paper):
        return self.client.get(reverse("paper-detail", args=[paper.id])).status_code

    def test_journal_version_paper_is_retrievable(self):
        # Act & Assert
        self.assertEqual(self._status(self.journal_paper), status.HTTP_200_OK)

    def test_listed_journal_paper_is_retrievable(self):
        # Act & Assert
        self.assertEqual(self._status(self.listed_paper), status.HTTP_200_OK)

    def test_versionless_original_of_journal_paper_is_retrievable(self):
        # Arrange
        original = create_paper(title="Original without a version row")
        PaperVersion.objects.create(
            paper=create_paper(title="Journal version 2"),
            version=2,
            original_paper=original,
            journal=PaperVersion.RESEARCHHUB,
        )

        # Act & Assert
        self.assertEqual(self._status(original), status.HTTP_200_OK)

    def test_other_paper_is_not_found(self):
        # Arrange
        self.client.force_authenticate(create_random_authenticated_user("reader"))

        # Act & Assert
        self.assertEqual(self._status(self.other_paper), status.HTTP_404_NOT_FOUND)

    def test_moderator_can_retrieve_other_paper(self):
        # Arrange
        moderator = create_random_authenticated_user("journal_mod", moderator=True)
        self.client.force_authenticate(moderator)

        # Act & Assert
        self.assertEqual(self._status(self.other_paper), status.HTTP_200_OK)
