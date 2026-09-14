from rest_framework.test import APITestCase

from hub.tests.helpers import create_hub
from paper.tests.helpers import create_paper
from user.tests.helpers import (
    create_random_authenticated_user,
    create_random_default_user,
)


class HubViewsTests(APITestCase):
    def setUp(self):
        self.base_url = "/api/hub/"
        self.hub = create_hub(name="View Test Hub")
        self.hub2 = create_hub(name="View Test Hub 2")
        self.user = create_random_authenticated_user("hub_user")

    def test_hub_order_by_paper_count(self):
        hub = create_hub("High Paper Count Hub")
        hub2 = create_hub("Low Paper Count Hub")

        paper = create_paper()
        hub.related_documents.add(paper.unified_document)
        hub.paper_count = 1
        hub.save()

        # this is a specific ordering used for the front end
        url = self.base_url + "?ordering=-paper_count,-discussion_count,id"
        response = self.client.get(url)
        response_data = response.data["results"]

        h1_first = False
        h2_second = False
        for h in response_data:
            if h["id"] == hub.id:
                h1_first = True
            elif h1_first and h["id"] == hub2.id:
                h2_second = True

        self.assertTrue(h1_first and h2_second)

    def test_hub_order_by_name(self):
        hub = create_hub("Hub A")
        hub2 = create_hub("Hub B")

        url = self.base_url + "?ordering=name"
        response = self.client.get(url)
        response_data = response.data["results"]

        h1_first = False
        h2_second = False
        for h in response_data:
            if h["id"] == hub.id:
                h1_first = True
            elif h1_first and h["id"] == hub2.id:
                h2_second = True

        self.assertTrue(h1_first and h2_second)

        url = self.base_url + "?ordering=-name"
        response = self.client.get(url)
        response_data = response.data["results"]

        h2_first = False
        h1_second = False
        for h in response_data:
            if h["id"] == hub2.id:
                h2_first = True
            elif h2_first and h["id"] == hub.id:
                h1_second = True

        self.assertTrue(h2_first and h1_second)

    def test_hub_is_paginated(self):
        for x in range(11):
            create_hub(name=f"Hub {x}")

        page = 1
        url = self.base_url + f"?page={page}&page_limit=10"
        response = self.client.get(url)
        result_count = len(response.data["results"])
        page1_ids = [h["id"] for h in response.data["results"]]

        self.assertEqual(result_count, 10)

        page = 2
        url = self.base_url + f"?page={page}&page_limit=10"
        response = self.client.get(url)
        result_count = len(response.data["results"])
        page2_ids = [h["id"] for h in response.data["results"]]

        self.assertLess(result_count, 10)
        for id in page1_ids:
            self.assertNotIn(id, page2_ids)

    def create_users(self, amount):
        users = []
        for x in range(amount):
            user = create_random_default_user(f"users{x}")
            users.append(user)
        return users

    def test_exclude_journals_parameter(self):
        """Test that exclude_journals parameter filters out journal hubs"""
        # Create a journal hub
        create_hub(name="Journal Hub", namespace="journal")

        # Test with exclude_journals=true
        response = self.client.get(self.base_url + "?exclude_journals=true")
        results = response.data["results"]
        self.assertEqual(len(results), 2)  # includes self.hub and self.hub2 from setUp
        hub_names = [h["name"] for h in results]
        self.assertNotIn("Journal Hub", hub_names)

    def test_include_journals_parameter(self):
        """Test that exclude_journals=false includes journal hubs"""

        # Test with exclude_journals=false
        response = self.client.get(self.base_url + "?exclude_journals=false")
        self.assertEqual(
            len(response.data["results"]), 2
        )  # includes self.hub and self.hub2 from setUp
