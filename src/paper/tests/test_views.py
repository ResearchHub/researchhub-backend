import json
import random
from unittest.mock import PropertyMock, patch

from django.test import Client, TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from hub.models import Hub
from paper.models import Paper, PaperVersion
from paper.related_models.authorship_model import Authorship
from paper.tests.helpers import create_paper
from paper.views.paper_views import PaperViewSet
from user.models import Author
from user.tests.helpers import create_random_authenticated_user, create_user
from utils.openalex import OpenAlex
from utils.test_helpers import (
    create_test_user,
    get_authenticated_get_response,
    get_authenticated_post_response,
)


class PaperApiTests(APITestCase):
    @patch.object(OpenAlex, "get_data_from_doi")
    @patch.object(OpenAlex, "get_works")
    def test_fetches_author_works_by_doi_if_name_matches(
        self, mock_get_works, mock_get_data_from_doi
    ):
        with open("./paper/tests/openalex_author_works.json", "r") as works_file, open(
            "./paper/tests/openalex_single_work.json", "r"
        ) as single_work_file:
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
        with open("./paper/tests/openalex_author_works.json", "r") as works_file, open(
            "./paper/tests/openalex_single_work.json", "r"
        ) as single_work_file:
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
        with open("./paper/tests/openalex_author_works.json", "r") as works_file, open(
            "./paper/tests/openalex_single_work.json", "r"
        ) as single_work_file:
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

    def test_create_researchhub_paper_creates_first_version(self):
        """Test that creating a new paper sets version 1"""
        user = create_random_authenticated_user("test_user")
        self.client.force_authenticate(user)
        hub = Hub.objects.create(name="Test Hub")
        author = Author.objects.create(first_name="Test", last_name="Author")

        data = {
            "title": "Test Paper",
            "abstract": "Test abstract",
            "authors": [
                {"id": author.id, "author_position": "first", "is_corresponding": True}
            ],
            "hub_ids": [hub.id],
            "declarations": [
                {"declaration_type": "ACCEPT_TERMS_AND_CONDITIONS", "accepted": True},
                {"declaration_type": "AUTHORIZE_CC_BY_4_0", "accepted": True},
                {"declaration_type": "CONFIRM_AUTHORS_RIGHTS", "accepted": True},
                {
                    "declaration_type": "CONFIRM_ORIGINALITY_AND_COMPLIANCE",
                    "accepted": True,
                },
            ],
        }

        response = self.client.post(
            "/api/paper/create_researchhub_paper/", data, format="json"
        )

        self.assertEqual(response.status_code, 201)
        paper_version = PaperVersion.objects.get(paper_id=response.data["id"])
        self.assertEqual(paper_version.version, 1)
        self.assertEqual(paper_version.original_paper_id, response.data["id"])
        paper = Paper.objects.get(id=response.data["id"])
        self.assertEqual(paper.title, "Test Paper")
        self.assertEqual(paper.abstract, "Test abstract")
        self.assertEqual(paper.pdf_license, "CC BY")
        hubs = paper.unified_document.hubs.all()
        self.assertEqual(len(hubs), 1)
        self.assertEqual(hubs[0].id, hub.id)

        authorship = paper.authorships.first()
        self.assertEqual(authorship.author.id, author.id)
        self.assertEqual(authorship.author_position, "first")
        self.assertTrue(authorship.is_corresponding)

        self.assertEqual(paper.hubs.first().id, hub.id)

    def test_create_researchhub_paper_with_multiple_authors(self):
        """Test creating a paper with multiple authors in different positions"""
        user = create_random_authenticated_user("test_user")
        self.client.force_authenticate(user)

        first_author = Author.objects.create(first_name="First", last_name="Author")
        middle_author = Author.objects.create(first_name="Middle", last_name="Author")
        last_author = Author.objects.create(first_name="Last", last_name="Author")

        data = {
            "title": "Test Paper",
            "abstract": "Test abstract",
            "authors": [
                {
                    "id": first_author.id,
                    "author_position": "first",
                    "is_corresponding": True,
                },
                {
                    "id": middle_author.id,
                    "author_position": "middle",
                    "is_corresponding": False,
                },
                {
                    "id": last_author.id,
                    "author_position": "last",
                    "is_corresponding": False,
                },
            ],
            "hub_ids": [],
            "declarations": [
                {"declaration_type": "ACCEPT_TERMS_AND_CONDITIONS", "accepted": True},
                {"declaration_type": "AUTHORIZE_CC_BY_4_0", "accepted": True},
                {"declaration_type": "CONFIRM_AUTHORS_RIGHTS", "accepted": True},
                {
                    "declaration_type": "CONFIRM_ORIGINALITY_AND_COMPLIANCE",
                    "accepted": True,
                },
            ],
        }

        response = self.client.post(
            "/api/paper/create_researchhub_paper/", data, format="json"
        )

        self.assertEqual(response.status_code, 201)
        paper = Paper.objects.get(id=response.data["id"])
        authorships = paper.authorships.all().order_by("author_position")

        self.assertEqual(len(authorships), 3)
        self.assertEqual(authorships[0].author.id, first_author.id)
        self.assertEqual(authorships[0].author_position, "first")
        self.assertTrue(authorships[0].is_corresponding)

        self.assertEqual(authorships[1].author.id, last_author.id)
        self.assertEqual(authorships[1].author_position, "last")
        self.assertFalse(authorships[1].is_corresponding)

        self.assertEqual(authorships[2].author.id, middle_author.id)
        self.assertEqual(authorships[2].author_position, "middle")
        self.assertFalse(authorships[2].is_corresponding)

    def test_create_researchhub_paper_requires_corresponding_author(self):
        """Test that at least one corresponding author is required"""
        user = create_random_authenticated_user("test_user")
        self.client.force_authenticate(user)
        author = Author.objects.create(first_name="Test", last_name="Author")

        data = {
            "title": "Test Paper",
            "abstract": "Test abstract",
            "authors": [
                {"id": author.id, "author_position": "first", "is_corresponding": False}
            ],
            "hub_ids": [],
            "declarations": [
                {"declaration_type": "ACCEPT_TERMS_AND_CONDITIONS", "accepted": True},
                {"declaration_type": "AUTHORIZE_CC_BY_4_0", "accepted": True},
                {"declaration_type": "CONFIRM_AUTHORS_RIGHTS", "accepted": True},
                {
                    "declaration_type": "CONFIRM_ORIGINALITY_AND_COMPLIANCE",
                    "accepted": True,
                },
            ],
        }

        response = self.client.post(
            "/api/paper/create_researchhub_paper/", data, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("corresponding author is required", str(response.data["error"]))

    def test_create_researchhub_paper_increments_version(self):
        """Test that creating a new version of an existing paper increments the version number"""
        # Create initial paper
        original_paper = create_paper()
        PaperVersion.objects.create(
            paper=original_paper, version=2, original_paper=original_paper
        )
        author = Author.objects.create(first_name="Test", last_name="Author")

        user = create_random_authenticated_user("test_user")
        self.client.force_authenticate(user)

        data = {
            "title": "Updated Test Paper",
            "abstract": "Updated abstract",
            "authors": [
                {"id": author.id, "author_position": "first", "is_corresponding": True}
            ],
            "hub_ids": [],
            "declarations": [
                {"declaration_type": "ACCEPT_TERMS_AND_CONDITIONS", "accepted": True},
                {"declaration_type": "AUTHORIZE_CC_BY_4_0", "accepted": True},
                {"declaration_type": "CONFIRM_AUTHORS_RIGHTS", "accepted": True},
                {
                    "declaration_type": "CONFIRM_ORIGINALITY_AND_COMPLIANCE",
                    "accepted": True,
                },
            ],
            "previous_paper_id": original_paper.id,
            "change_description": "Updated content",
        }

        response = self.client.post(
            "/api/paper/create_researchhub_paper/", data, format="json"
        )

        self.assertEqual(response.status_code, 201)
        paper_version = PaperVersion.objects.get(paper_id=response.data["id"])
        self.assertEqual(paper_version.version, 3)
        self.assertEqual(paper_version.message, "Updated content")
        self.assertEqual(paper_version.original_paper_id, original_paper.id)

    def test_create_researchhub_paper_with_valid_previous_paper_no_version(self):
        """Test creating a new paper with a valid previous_paper_id that has no versions"""
        user = create_random_authenticated_user("test_user")
        self.client.force_authenticate(user)
        author = Author.objects.create(first_name="Test", last_name="Author")

        previous_paper = create_paper()

        data = {
            "title": "Test Paper",
            "abstract": "Test abstract",
            "authors": [
                {"id": author.id, "author_position": "first", "is_corresponding": True}
            ],
            "hub_ids": [],
            "declarations": [
                {"declaration_type": "ACCEPT_TERMS_AND_CONDITIONS", "accepted": True},
                {"declaration_type": "AUTHORIZE_CC_BY_4_0", "accepted": True},
                {"declaration_type": "CONFIRM_AUTHORS_RIGHTS", "accepted": True},
                {
                    "declaration_type": "CONFIRM_ORIGINALITY_AND_COMPLIANCE",
                    "accepted": True,
                },
            ],
            "previous_paper_id": previous_paper.id,
        }

        response = self.client.post(
            "/api/paper/create_researchhub_paper/", data, format="json"
        )

        self.assertEqual(response.status_code, 201)
        paper = Paper.objects.get(id=response.data["id"])
        self.assertEqual(paper.title, "Test Paper")
        self.assertEqual(paper.abstract, "Test abstract")
        self.assertEqual(previous_paper.version.version, 1)
        self.assertEqual(paper.version.version, 2)

    def test_create_researchhub_paper_with_invalid_previous_paper(self):
        """Test handling of invalid previous_paper_id"""
        user = create_random_authenticated_user("test_user")
        self.client.force_authenticate(user)
        author = Author.objects.create(first_name="Test", last_name="Author")

        data = {
            "title": "Test Paper",
            "abstract": "Test abstract",
            "authors": [
                {"id": author.id, "author_position": "first", "is_corresponding": True}
            ],
            "hub_ids": [],
            "declarations": [
                {"declaration_type": "ACCEPT_TERMS_AND_CONDITIONS", "accepted": True},
                {"declaration_type": "AUTHORIZE_CC_BY_4_0", "accepted": True},
                {"declaration_type": "CONFIRM_AUTHORS_RIGHTS", "accepted": True},
                {
                    "declaration_type": "CONFIRM_ORIGINALITY_AND_COMPLIANCE",
                    "accepted": True,
                },
            ],
            "previous_paper_id": 99999,  # Non-existent ID
        }

        response = self.client.post(
            "/api/paper/create_researchhub_paper/", data, format="json"
        )

        self.assertEqual(response.status_code, 400)

    def test_create_researchhub_paper_requires_title_and_abstract(self):
        """Test validation of required fields"""
        user = create_random_authenticated_user("test_user")
        self.client.force_authenticate(user)

        # Missing title
        data = {
            "abstract": "Test abstract",
            "authors": [],
            "hub_ids": [],
            "declarations": [
                {"declaration_type": "ACCEPT_TERMS_AND_CONDITIONS", "accepted": True},
                {"declaration_type": "AUTHORIZE_CC_BY_4_0", "accepted": True},
                {"declaration_type": "CONFIRM_AUTHORS_RIGHTS", "accepted": True},
                {
                    "declaration_type": "CONFIRM_ORIGINALITY_AND_COMPLIANCE",
                    "accepted": True,
                },
            ],
        }

        response = self.client.post(
            "/api/paper/create_researchhub_paper/", data, format="json"
        )

        self.assertEqual(response.status_code, 400)

        # Missing abstract
        data = {"title": "Test Paper", "authors": [], "hub_ids": []}

        response = self.client.post(
            "/api/paper/create_researchhub_paper/", data, format="json"
        )

        self.assertEqual(response.status_code, 400)

    def test_create_researchhub_paper_with_unaccepted_declarations(self):
        """Test that paper creation fails if valid declarations are not accepted"""
        user = create_random_authenticated_user("test_user")
        self.client.force_authenticate(user)
        author = Author.objects.create(first_name="Test", last_name="Author")

        data = {
            "title": "Test Paper",
            "abstract": "Test abstract",
            "authors": [
                {"id": author.id, "author_position": "first", "is_corresponding": True}
            ],
            "hub_ids": [],
            "declarations": [
                {"declaration_type": "ACCEPT_TERMS_AND_CONDITIONS", "accepted": False},
                {"declaration_type": "AUTHORIZE_CC_BY_4_0", "accepted": True},
                {"declaration_type": "CONFIRM_AUTHORS_RIGHTS", "accepted": True},
                {
                    "declaration_type": "CONFIRM_ORIGINALITY_AND_COMPLIANCE",
                    "accepted": True,
                },
            ],
        }

        response = self.client.post(
            "/api/paper/create_researchhub_paper/", data, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            "All declarations must be accepted to continue.",
            response.data["error"],
        )

    def test_create_researchhub_paper_with_missing_declarations(self):
        """Test that paper creation fails if valid declarations are not accepted"""
        user = create_random_authenticated_user("test_user")
        self.client.force_authenticate(user)
        author = Author.objects.create(first_name="Test", last_name="Author")

        data = {
            "title": "Test Paper",
            "abstract": "Test abstract",
            "authors": [
                {"id": author.id, "author_position": "first", "is_corresponding": True}
            ],
            "hub_ids": [],
            "declarations": [
                {"declaration_type": "ACCEPT_TERMS_AND_CONDITIONS", "accepted": True},
            ],
        }

        response = self.client.post(
            "/api/paper/create_researchhub_paper/", data, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            "Please accept all required declarations to continue.",
            str(response.data["error"]),
        )


class PaperViewsTests(TestCase):
    def setUp(self):
        SEED = "paper"
        self.random_generator = random.Random(SEED)
        self.base_url = "/api/paper/"
        self.paper = create_paper()
        self.user = create_random_authenticated_user("paper_views_user")
        self.trouble_maker = create_random_authenticated_user("trouble_maker")

    def test_check_url_is_true_if_url_has_pdf(self):
        url = self.base_url + "check_url/"
        data = {"url": "https://bitcoin.org/bitcoin.pdf"}
        response = get_authenticated_post_response(self.user, url, data)
        self.assertContains(response, "true", status_code=200)

    def test_check_url_is_false_if_url_does_NOT_have_pdf(self):
        url = self.base_url + "check_url/"
        data = {"url": "https://bitcoin.org/en/"}
        response = get_authenticated_post_response(self.user, url, data)
        self.assertContains(response, "false", status_code=200)

    def test_check_url_is_false_for_malformed_url(self):
        url = self.base_url + "check_url/"
        data = {"url": "bitcoin.org/bitcoin.pdf/"}
        response = get_authenticated_post_response(self.user, url, data)
        self.assertContains(response, "false", status_code=200)

        data = {"url": "bitcoin"}
        response = get_authenticated_post_response(self.user, url, data)
        self.assertContains(response, "false", status_code=200)

    def test_api_token_can_upload_paper(self):
        api_token_url = "/api/user_external_token/"
        api_token_response = get_authenticated_post_response(
            self.user, api_token_url, {}
        )
        token = api_token_response.json().get("token", "")
        api_token_client = Client(HTTP_RH_API_KEY=token)
        res = api_token_client.post(
            self.base_url,
            {"title": "Paper Uploaded via API Token", "paper_type": "REGULAR"},
        )
        self.assertEqual(res.status_code, 201)

    @patch.object(Paper, "paper_rewards", new_callable=PropertyMock)
    def test_eligible_reward_summary(self, mock_get_paper_reward):
        url = self.base_url + f"{self.paper.id}/eligible_reward_summary/"
        mock_get_paper_reward.return_value = 100
        response = get_authenticated_get_response(self.user, url, {})

        self.assertEqual(response.status_code, 200)
        result = response.data
        self.assertEqual(result["base_rewards"], 100)

    def test_search_by_url_bad(self):
        url = self.base_url + "search_by_url/"
        data = {"url": "org/this-is-a-bad-url"}
        response = get_authenticated_post_response(self.user, url, data)
        self.assertContains(response, "Double check that URL", status_code=400)


class PaperDOITests(APITestCase):
    def setUp(self):
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

    @patch("utils.openalex.OpenAlex.get_work_by_doi")
    def test_retrieve_by_doi_new_paper_from_openalex(self, mock_get_work):
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
                        "id": "A123",
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
