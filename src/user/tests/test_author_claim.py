from rest_framework.test import APITestCase

from user.tests.helpers import create_user


class AuthorClaimTests(APITestCase):
    def setUp(self):
        self.user = create_user(email="random@example.com")

    def test_user_can_claim_openalex_profile_if_not_already_claimed(self):
        pass

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
