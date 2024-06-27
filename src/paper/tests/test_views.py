import json
import random
from unittest import skip
from unittest.mock import patch

from django.test import Client, TestCase
from rest_framework.test import APITestCase

from paper.tests.helpers import create_paper
from user.tests.helpers import create_random_authenticated_user, create_user
from utils.openalex import OpenAlex
from utils.test_helpers import (
    get_authenticated_delete_response,
    get_authenticated_post_response,
)


class PaperApiTests(APITestCase):
    @patch.object(OpenAlex, "get_data_from_doi")
    @patch.object(OpenAlex, "get_works")
    def test_fetches_author_works_by_doi_if_name_matches(
        self, mock_get_works, mock_get_data_from_doi
    ):
        print("TEST TO SEE IF THIS IS RUNNING ON GITHUB ")
        with open("./paper/tests/openalex_author_works.json", "r") as works_file:
            with open(
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
                    f"/api/paper/fetch_openalex_works_by_doi/?doi=10.1371/journal.pone.0305345",
                )

                self.assertGreater(len(response.data["works"]), 0)

    @patch.object(OpenAlex, "get_data_from_doi")
    @patch.object(OpenAlex, "get_works")
    def test_cannot_fetch_author_works_by_doi_if_name_mismatch(
        self, mock_get_works, mock_get_data_from_doi
    ):
        with open("./paper/tests/openalex_author_works.json", "r") as works_file:
            with open(
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
                    f"/api/paper/fetch_openalex_works_by_doi/?doi=10.1371/journal.pone.0305345",
                )

                self.assertEqual(len(response.data["works"]), 0)
                self.assertGreater(len(response.data["available_authors"]), 0)

    @patch.object(OpenAlex, "get_data_from_doi")
    @patch.object(OpenAlex, "get_works")
    def test_fetch_author_works_by_doi_can_accept_optional_author_id(
        self, mock_get_works, mock_get_data_from_doi
    ):
        with open("./paper/tests/openalex_author_works.json", "r") as works_file:
            with open(
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
                    f"/api/paper/fetch_openalex_works_by_doi/?doi=10.1371/journal.pone.0305345&author_id={author_id}",
                )

                self.assertEqual(response.data["selected_author_id"], author_id)


class PaperViewsTests(TestCase):
    def setUp(self):
        SEED = "paper"
        self.random_generator = random.Random(SEED)
        self.base_url = "/api/paper/"
        self.paper = create_paper()
        self.user = create_random_authenticated_user("paper_views_user")
        self.trouble_maker = create_random_authenticated_user("trouble_maker")

    def test_can_bookmark_paper(self):
        response = self.get_bookmark_post_response(self.user)
        self.assertContains(response, self.paper.title, status_code=201)

    def test_can_delete_bookmark(self):
        response = self.get_bookmark_delete_response(self.user)
        self.assertContains(response, self.paper.id, status_code=200)

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
        self.assertEquals(res.status_code, 201)

    @skip
    def test_search_by_url_arxiv(self):
        url = self.base_url + "search_by_url/"
        data = {"url": "https://arxiv.org/abs/1407.3561v1", "search": True}
        response = get_authenticated_post_response(self.user, url, data)
        self.assertEquals(response.status_code, 200)
        result = response.data
        self.assertEquals(result["url"], data["url"])
        self.assertFalse(result["url_is_pdf"])
        self.assertEquals(
            result["csl_item"]["title"],
            "IPFS - Content Addressed, Versioned, P2P File System",
        )
        self.assertEqual(
            result["oa_pdf_location"]["url_for_pdf"],
            "https://arxiv.org/pdf/1407.3561v1.pdf",
        )
        self.assertIsInstance(result["search"], list)

    @skip
    def test_search_by_url_arxiv_pdf(self):
        url = self.base_url + "search_by_url/"
        data = {"url": "https://arxiv.org/pdf/1407.3561.pdf"}
        response = get_authenticated_post_response(self.user, url, data)
        self.assertEquals(response.status_code, 200)
        result = response.data
        self.assertEquals(result["url"], data["url"])
        self.assertTrue(result["url_is_pdf"])
        self.assertFalse(result["url_is_unsupported_pdf"])
        self.assertEquals(
            result["csl_item"]["title"],
            "IPFS - Content Addressed, Versioned, P2P File System",
        )
        pdf_location = result["oa_pdf_location"]
        self.assertEqual(
            pdf_location["url_for_pdf"], "https://arxiv.org/pdf/1407.3561.pdf"
        )
        self.assertEqual(pdf_location["license"], "cc-by")
        self.assertEqual(
            pdf_location["url_for_landing_page"], "https://arxiv.org/abs/1407.3561"
        )
        self.assertFalse("search" in result)

    @skip
    def test_search_by_url_publisher(self):
        url = self.base_url + "search_by_url/"
        data = {"url": "https://www.nature.com/articles/s41586-019-1099-1"}
        response = get_authenticated_post_response(self.user, url, data)
        self.assertEquals(response.status_code, 200)
        result = response.data
        self.assertEquals(result["url"], data["url"])
        self.assertFalse(result["url_is_pdf"])
        self.assertFalse(result["url_is_unsupported_pdf"])
        self.assertEquals(
            result["csl_item"]["title"],
            "Restoration of brain circulation and cellular functions hours post-mortem",
        )  # noqa E501
        self.assertEquals(result["csl_item"]["DOI"], "10.1038/s41586-019-1099-1")

    @skip
    def test_search_by_url_doi(self):
        url = self.base_url + "search_by_url/"
        data = {"url": "https://doi.org/10.1038/ng.3259"}
        response = get_authenticated_post_response(self.user, url, data)
        self.assertEquals(response.status_code, 200)
        result = response.data
        self.assertEquals(result["url"], data["url"])
        self.assertFalse(result["url_is_pdf"])
        self.assertFalse(result["url_is_unsupported_pdf"])
        self.assertEquals(
            result["csl_item"]["title"],
            "Understanding multicellular function and disease with human tissue-specific networks",
        )  # noqa E501
        self.assertEquals(result["csl_item"]["DOI"], "10.1038/ng.3259")
        self.assertEquals(
            result["oa_pdf_location"]["url_for_pdf"],
            "http://europepmc.org/articles/pmc4828725?pdf=render",
        )

    @skip
    def test_search_by_url_pmid(self):
        """
        Search by PMID without a DOI from an inactive journal
        """
        url = self.base_url + "search_by_url/"
        data = {"url": "https://www.ncbi.nlm.nih.gov/pubmed/18888140"}
        response = get_authenticated_post_response(self.user, url, data)
        self.assertEquals(response.status_code, 200)
        result = response.data
        self.assertEquals(result["url"], data["url"])
        self.assertFalse(result["url_is_pdf"])
        self.assertFalse(result["url_is_unsupported_pdf"])
        self.assertEquals(
            result["csl_item"]["title"],
            "[Major achievements in the second plan year in the Soviet Union].",
        )  # noqa E501
        self.assertIsNone(result["oa_pdf_location"])

    @skip
    def test_search_by_url_unsupported_pdf(self):
        url = self.base_url + "search_by_url/"
        data = {"url": "https://bitcoin.org/bitcoin.pdf"}
        response = get_authenticated_post_response(self.user, url, data)
        self.assertEquals(response.status_code, 200)
        result = response.data
        self.assertTrue(result["url_is_pdf"])
        self.assertTrue(result["url_is_unsupported_pdf"])
        self.assertEqual(result["csl_item"]["URL"], data["url"])
        self.assertEqual(result["oa_pdf_location"]["url_for_pdf"], data["url"])

    def test_search_by_url_bad(self):
        url = self.base_url + "search_by_url/"
        data = {"url": "org/this-is-a-bad-url"}
        response = get_authenticated_post_response(self.user, url, data)
        self.assertContains(response, "Double check that URL", status_code=400)

    def get_bookmark_post_response(self, user):
        url = self.base_url + f"{self.paper.id}/bookmark/"
        data = None
        response = get_authenticated_post_response(
            user, url, data, content_type="application/json"
        )
        return response

    def get_bookmark_delete_response(self, user):
        url = self.base_url + f"{self.paper.id}/bookmark/"
        data = None
        response = get_authenticated_delete_response(
            user, url, data, content_type="application/json"
        )
        return response
