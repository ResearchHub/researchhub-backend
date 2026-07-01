import json
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from paper.models import Paper
from paper.related_models.authorship_model import Authorship
from paper.tests.helpers import create_paper
from paper.views.paper_views import PaperViewSet
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import (
    create_random_authenticated_user,
    create_user,
)
from utils.openalex import OpenAlex
from utils.test_helpers import create_test_user

fixtures_dir = Path(__file__).parent / "fixtures"


class PaperApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch.object(OpenAlex, "get_data_from_doi")
    @patch.object(OpenAlex, "get_works")
    def test_fetches_author_works_by_doi_if_name_matches(
        self, mock_get_works, mock_get_data_from_doi
    ):
        with (
            open(fixtures_dir / "openalex_author_works.json") as works_file,
            open(fixtures_dir / "openalex_single_work.json") as single_work_file,
        ):
            # Set up a user that has a matching name to the one in the mocked response
            user_with_published_works = create_user(
                first_name="Yang",
                last_name="Wang",
                email="random_author@researchhub.com",
            )
            self.client.force_authenticate(user_with_published_works)

            # Mock responses for OpenAlex API calls
            mock_data = json.load(works_file)
            mock_get_works.return_value = (mock_data["results"], None)
            mock_get_data_from_doi.return_value = json.load(single_work_file)

            response = self.client.get(
                "/api/paper/fetch_publications_by_doi/?doi=10.1371/journal.pone.0305345",
            )

            self.assertGreater(len(response.data["works"]), 0)

    @patch.object(OpenAlex, "get_data_from_doi")
    @patch.object(OpenAlex, "get_works")
    def test_cannot_fetch_author_works_by_doi_if_name_mismatch(
        self, mock_get_works, mock_get_data_from_doi
    ):
        with (
            open(fixtures_dir / "openalex_author_works.json") as works_file,
            open(fixtures_dir / "openalex_single_work.json") as single_work_file,
        ):
            # Set up a user that has a matching name to the one in the mocked response
            user_with_published_works = create_user(
                first_name="Name",
                last_name="Mismatch",
                email="random_author@researchhub.com",
            )
            self.client.force_authenticate(user_with_published_works)

            # Mock responses for OpenAlex API calls
            mock_data = json.load(works_file)
            mock_get_works.return_value = (mock_data["results"], None)
            mock_get_data_from_doi.return_value = json.load(single_work_file)

            response = self.client.get(
                "/api/paper/fetch_publications_by_doi/?doi=10.1371/journal.pone.0305345",
            )

            self.assertEqual(len(response.data["works"]), 0)
            self.assertGreater(len(response.data["available_authors"]), 0)

    @patch.object(OpenAlex, "get_data_from_doi")
    @patch.object(OpenAlex, "get_works")
    def test_fetch_author_works_by_doi_can_accept_optional_author_id(
        self, mock_get_works, mock_get_data_from_doi
    ):
        with (
            open(fixtures_dir / "openalex_author_works.json") as works_file,
            open(fixtures_dir / "openalex_single_work.json") as single_work_file,
        ):
            # Set up a user that has a matching name to the one in the mocked response
            user_with_published_works = create_user(
                first_name="Name",
                last_name="Mismatch",
                email="random_author@researchhub.com",
            )
            self.client.force_authenticate(user_with_published_works)

            # Mock responses for OpenAlex API calls
            mock_data = json.load(works_file)
            mock_get_works.return_value = (mock_data["results"], None)
            mock_get_data_from_doi.return_value = json.load(single_work_file)

            # Override author guessing by explicilty providing author_id
            author_id = "A5075662890"

            response = self.client.get(
                f"/api/paper/fetch_publications_by_doi/?doi=10.1371/journal.pone.0305345&author_id={author_id}",
            )

            self.assertEqual(response.data["selected_author_id"], author_id)

    def test_filter_unclaimed_works(self):
        # Arrange
        author = create_user(first_name="test_unclaimed_works").author_profile
        openalex_works = [{"id": "openalex1"}, {"id": "openalex2"}, {"id": "openalex3"}]

        paper = Paper.objects.create(openalex_id="openalex2")
        Authorship.objects.create(author=author, paper=paper)

        # Act
        unclaimed_works = PaperViewSet()._filter_unclaimed_works(author, openalex_works)

        # Assert
        self.assertEqual(len(unclaimed_works), 2)
        self.assertEqual(unclaimed_works, [{"id": "openalex1"}, {"id": "openalex3"}])

    def test_filter_unclaimed_works_all_claimed(self):
        # Arrange
        author = create_user(first_name="test_unclaimed_works").author_profile
        openalex_works = [{"id": "openalex1"}, {"id": "openalex2"}, {"id": "openalex3"}]

        paper1 = Paper.objects.create(openalex_id="openalex1")
        paper2 = Paper.objects.create(openalex_id="openalex2")
        paper3 = Paper.objects.create(openalex_id="openalex3")

        Authorship.objects.create(author=author, paper=paper1)
        Authorship.objects.create(author=author, paper=paper2)
        Authorship.objects.create(author=author, paper=paper3)

        # Act
        unclaimed_works = PaperViewSet()._filter_unclaimed_works(author, openalex_works)

        # Assert
        self.assertEqual(unclaimed_works, [])

    def test_filter_unclaimed_works_none_claimed(self):
        # Arrange
        author = create_user(first_name="test_unclaimed_works").author_profile
        openalex_works = [{"id": "openalex1"}, {"id": "openalex2"}, {"id": "openalex3"}]

        # Act
        unclaimed_works = PaperViewSet()._filter_unclaimed_works(author, openalex_works)

        # Assert
        self.assertEqual(len(unclaimed_works), 3)
        self.assertEqual(unclaimed_works, openalex_works)

class PaperDOITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = create_test_user()
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
        self.pending_paper = create_paper(
            title="Pending paper", uploaded_by=self.uploader
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
