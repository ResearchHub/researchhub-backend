import json
from unittest.mock import patch

from rest_framework.test import APITestCase

from paper.related_models.paper_model import Paper
from user.tests.helpers import create_user
from utils.openalex import OpenAlex


class AuthorClaimTests(APITestCase):
    def setUp(self):
        self.user = create_user(email="random@example.com")

    @patch.object(OpenAlex, "get_authors")
    @patch.object(OpenAlex, "get_works")
    def test_user_can_claim_openalex_profile_if_not_already_claimed(
        self, mock_get_works, mock_get_authors
    ):
        with open("./user/tests/openalex_authors.json", "r") as authors_file:
            authors_data = json.load(authors_file)["results"]

            with open("./paper/tests/openalex_author_works.json", "r") as works_file:
                works_data = json.load(works_file)["results"]
                mock_get_works.return_value = (works_data, None)
                mock_get_authors.return_value = (authors_data, None)

                claiming_user_openalex_id = "https://openalex.org/A5068835581"
                claiming_user = create_user(
                    first_name="Yang",
                    last_name="Wang",
                    email="random_author@researchhub.com",
                )

                self.client.force_authenticate(claiming_user)

                # Get author work Ids first
                openalex_api = OpenAlex()
                results, cursor = openalex_api.get_works()
                work_ids = [work["id"] for work in results]

                # # Add publications to author
                url = f"/api/author/{claiming_user.author_profile.id}/claim_profile_and_add_publications/"
                response = self.client.post(
                    url,
                    {
                        "openalex_ids": work_ids,
                        "openalex_author_id": claiming_user_openalex_id,
                    },
                )

                claiming_user.refresh_from_db()
                self.assertEqual(
                    claiming_user_openalex_id
                    in claiming_user.author_profile.openalex_ids,
                    True,
                )

    @patch.object(OpenAlex, "get_authors")
    @patch.object(OpenAlex, "get_works")
    def test_claiming_user_should_have_publications_in_their_profile(
        self, mock_get_works, mock_get_authors
    ):
        with open("./user/tests/openalex_authors.json", "r") as authors_file:
            authors_data = json.load(authors_file)["results"]

            with open("./paper/tests/openalex_author_works.json", "r") as works_file:
                works_data = json.load(works_file)["results"]
                mock_get_works.return_value = (works_data, None)
                mock_get_authors.return_value = (authors_data, None)

                claiming_user_openalex_id = "https://openalex.org/A5068835581"
                claiming_user = create_user(
                    first_name="Yang",
                    last_name="Wang",
                    email="random_author@researchhub.com",
                )

                self.client.force_authenticate(claiming_user)

                # Get author work Ids first
                openalex_api = OpenAlex()
                results, cursor = openalex_api.get_works()
                work_ids = [work["id"] for work in results]

                # # Add publications to author
                url = f"/api/author/{claiming_user.author_profile.id}/claim_profile_and_add_publications/"
                response = self.client.post(
                    url,
                    {
                        "openalex_ids": work_ids,
                        "openalex_author_id": claiming_user_openalex_id,
                    },
                )

                claiming_user.refresh_from_db()
                self.assertCountEqual(
                    [
                        p.openalex_id
                        for p in claiming_user.author_profile.authored_papers.all()
                    ],
                    work_ids,
                )

    @patch.object(OpenAlex, "get_authors")
    @patch.object(OpenAlex, "get_works")
    def test_claiming_user_should_have_openalex_stats_set_in_profile(
        self, mock_get_works, mock_get_authors
    ):
        with open("./user/tests/openalex_authors.json", "r") as authors_file:
            authors_data = json.load(authors_file)["results"]

            with open("./paper/tests/openalex_author_works.json", "r") as works_file:
                works_data = json.load(works_file)["results"]
                mock_get_works.return_value = (works_data, None)
                mock_get_authors.return_value = (authors_data, None)

                claiming_user_openalex_id = "https://openalex.org/A5068835581"
                claiming_user = create_user(
                    first_name="Yang",
                    last_name="Wang",
                    email="random_author@researchhub.com",
                )

                self.client.force_authenticate(claiming_user)

                # Get author work Ids first
                openalex_api = OpenAlex()
                results, cursor = openalex_api.get_works()
                work_ids = [work["id"] for work in results]

                # # Add publications to author
                url = f"/api/author/{claiming_user.author_profile.id}/claim_profile_and_add_publications/"
                response = self.client.post(
                    url,
                    {
                        "openalex_ids": work_ids,
                        "openalex_author_id": claiming_user_openalex_id,
                    },
                )

                claiming_user.refresh_from_db()
                openalex_author = authors_data[0]
                self.assertEqual(
                    claiming_user.author_profile.orcid_id, openalex_author.get("orcid")
                )
                self.assertEqual(
                    claiming_user.author_profile.two_year_mean_citedness,
                    openalex_author.get("summary_stats", {}).get("2yr_mean_citedness"),
                )
                self.assertEqual(
                    claiming_user.author_profile.h_index,
                    openalex_author.get("summary_stats", {}).get("h_index"),
                )

    def test_user_cannot_claim_openalex_profile_if_already_claimed_by_current_user(
        self,
    ):
        pass

    def test_user_cannot_claim_openalex_profile_if_already_claimed_by_another_user(
        self,
    ):
        pass

    def test_already_existing_author_profile_can_be_claimed_if_does_not_belong_to_any_user(
        self,
    ):
        pass

    def test_claimed_author_should_have_openalex_id(self):
        pass

    def test_unclaimed_author_profiles_with_claiming_user(self):
        pass
