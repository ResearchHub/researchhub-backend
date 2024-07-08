import json
from unittest.mock import patch

from rest_framework.test import APITestCase

from user.tests.helpers import create_user
from utils.openalex import OpenAlex


class AuthorClaimTests(APITestCase):
    def setUp(self):
        self.user = create_user(email="random@example.com")

    @patch.object(OpenAlex, "get_works")
    @patch.object(OpenAlex, "get_authors")
    def test_user_can_claim_openalex_profile_if_not_already_claimed(
        self, mock_get_works, mock_get_authors
    ):
        with open("./user/tests/openalex_authors.json", "r") as authors_file:
            with open("./paper/tests/openalex_author_works.json", "r") as works_file:
                mock_get_works.return_value = json.load(works_file)["results"]
                mock_get_authors.return_value = json.load(authors_file)["results"]

                user_with_published_works = create_user(
                    first_name="Yang",
                    last_name="Wang",
                    email="random_author@researchhub.com",
                )

                self.client.force_authenticate(user_with_published_works)

                # Get author work Ids first
                openalex_api = OpenAlex()
                author_works = openalex_api.get_works()
                work_ids = [work["id"] for work in author_works]

                print("workd_ids:", work_ids)

                # # Add publications to author
                # url = f"/api/author/{user_with_published_works.author_profile.id}/add_publications/"
                # response = self.client.post(
                #     url, {"openalex_ids": work_ids, "openalex_author_id": "A5068835581"}
                # )

                # # Verify at least one publication is created and credited to the author
                # paper = Paper.objects.get(openalex_id=author_works[0].get("id"))
                # self.assertEqual(
                #     paper.authors.filter(
                #         id=user_with_published_works.author_profile.id
                #     ).exists(),
                #     True,
                # )

    def test_claimed_user_should_have_openalex_stats_set_in_profile(self):
        pass

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
