from rest_framework.test import APITestCase

from user.tests.helpers import create_random_default_user


class CitationEntryViewTests(APITestCase):
    def setUp(self):
        self.authenticated_user = create_random_default_user("user1")

    def test_url_search(self):
        self.client.force_authenticate(self.authenticated_user)

        response = self.client.get(
            "/api/citation_entry/url_search/?url=https://staging-backend.researchhub.com/api/paper/1001/",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["doi"], "https://doi.org/10.1016/0370-2693(93)90747-6"
        )
