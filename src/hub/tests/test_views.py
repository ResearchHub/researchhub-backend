from math import ceil
from unittest import skip

from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from discussion.tests.helpers import create_thread
from hub.models import Hub
from hub.related_models import HubV2
from hub.tests.helpers import create_hub, create_hub_v2
from paper.tests.helpers import create_paper
from user.tests.helpers import (
    create_actions,
    create_random_authenticated_user,
    create_random_default_user,
)
from utils.test_helpers import get_authenticated_post_response, get_get_response


class HubViewsTests(APITestCase):
    def setUp(self):
        self.base_url = "/api/hub/"
        self.hub = create_hub(name="View Test Hub")
        self.hub2 = create_hub(name="View Test Hub 2")
        self.user = create_random_authenticated_user("hub_user")

    def test_basic_user_cannot_edit_hub(self):
        basic_user = create_random_authenticated_user("basic_user")
        self.client.force_authenticate(basic_user)
        hub = create_hub(name="some hub")

        response = self.client.put(
            f"/api/hub/{hub.id}/",
            {
                "name": "updated name",
                "id": hub.id,
                "description": "description",
            },
        )

        h = Hub.objects.get(id=hub.id)
        self.assertNotEqual(h.name, "updated name")

    def test_moderator_can_delete_hub(self):
        mod = create_random_authenticated_user("mod", moderator=True)
        self.client.force_authenticate(mod)
        hub = create_hub(name="some hub")

        response = self.client.delete(f"/api/hub/{hub.id}/censor/")

        self.assertTrue(response.status_code, 200)

    def test_basic_user_cannot_delete_hub(self):
        basic_user = create_random_authenticated_user("basic_user")
        self.client.force_authenticate(basic_user)
        hub = create_hub(name="some hub")

        response = self.client.delete(f"/api/hub/{hub.id}/censor/")

        self.assertTrue(response.status_code, 401)

    @skip
    def test_hub_order_by_score(self):
        hub = create_hub("High Score Hub")
        hub2 = create_hub("Low Score Hub")

        actions = create_actions(10, hub=hub)
        actions = create_actions(5, hub=hub2)

        url = self.base_url + "?ordering=-score"
        response = get_get_response(url)
        response_data = response.data["results"]

        h1_first = False
        h2_second = False
        for h in response_data:
            if h["id"] == hub.id:
                h1_first = True
            elif h1_first and h["id"] == hub2.id:
                h2_second = True

        self.assertTrue(h1_first and h2_second)
        cache.clear()
        url = self.base_url + "?ordering=score"
        response = get_get_response(url)
        response_data = response.data["results"]

        h2_first = False
        h1_second = False
        for h in response_data:
            if h["id"] == hub2.id:
                h2_first = True
            elif h2_first and h["id"] == hub.id:
                h1_second = True

        self.assertTrue(h2_first and h1_second)

    def test_can_subscribe_to_hub(self):
        start_state = self.is_subscribed(self.user, self.hub)
        self.assertFalse(start_state)

        self.get_hub_subscribe_response(self.user)

        self.hub.refresh_from_db()
        end_state = self.is_subscribed(self.user, self.hub)
        self.assertTrue(end_state)

    def test_can_unsubscribe_to_hub(self):
        self.hub.subscribers.add(self.user)
        self.hub.save()

        start_state = self.is_subscribed(self.user, self.hub)
        self.assertTrue(start_state)

        self.get_hub_unsubscribe_response(self.user)

        self.hub.refresh_from_db()
        end_state = self.is_subscribed(self.user, self.hub)
        self.assertFalse(end_state)

    def test_invite_to_hub(self):
        hub = create_hub("Invite to Hub")
        email = "val@quantfive.org"

        response = self.get_invite_to_hub_response(self.user, hub, [email])
        self.assertContains(response, email, status_code=200)

    def test_invite_to_hub_does_not_email_subscribers(self):
        subscriber = create_random_default_user("subscriber")
        subscriber.email = "val@quantfive.org"  # Must use whitelisted email
        subscriber.save()
        hub = create_hub("Invite to Hub No Email")
        hub.subscribers.add(subscriber)

        response = self.get_invite_to_hub_response(self.user, hub, [subscriber.email])
        self.assertNotContains(response, subscriber.email, status_code=200)

    @skip
    def test_hub_actions_is_paginated(self):
        hub = create_hub(name="Calpurnia")
        paper = create_paper()
        hub.papers.add(paper)

        for x in range(11):
            create_thread(paper=paper, created_by=self.user)
        page = 1
        url = self.base_url + f"{hub.id}/latest_actions/?page={page}"
        response = get_get_response(url)
        self.assertContains(response, 'count":11', status_code=200)
        result_count = len(response.data["results"])
        self.assertEqual(result_count, 10)

        page = 2
        url = self.base_url + f"{hub.id}/latest_actions/?page={page}"
        response = get_get_response(url)
        self.assertContains(response, 'count":11', status_code=200)
        result_count = len(response.data["results"])
        self.assertEqual(result_count, 1)

    def is_subscribed(self, user, hub):
        return user in hub.subscribers.all()

    def create_users(self, amount):
        users = []
        for x in range(amount):
            user = create_random_default_user(f"users{x}")
            users.append(user)
        return users

    def get_hub_subscribe_response(self, user, hub=None):
        if hub is None:
            hub = self.hub

        url = self.base_url + f"{hub.id}/subscribe/"
        return self.get_hub_response(url, user)

    def get_hub_unsubscribe_response(self, user):
        url = self.base_url + f"{self.hub.id}/unsubscribe/"
        return self.get_hub_response(url, user)

    def get_hub_response(self, url, user):
        data = None
        return get_authenticated_post_response(user, url, data)

    def get_invite_to_hub_response(self, user, hub, emails):
        url = self.base_url + f"{hub.id}/invite_to_hub/"
        data = {"emails": emails}
        return get_authenticated_post_response(
            user, url, data, headers={"HTTP_ORIGIN": "researchhub.com"}
        )


class HubV2ViewsTests(APITestCase):
    def test_cannot_create_hub(self):
        hub_id = "some-hub"
        path = "/api/hubs/"
        data = {
            "id": hub_id,
            "display_name": "updated name",
            "description": "description",
        }

        # Unauthenticated
        response = self.client.post(path, data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Basic user
        basic_user = create_random_authenticated_user("basic_user")
        self.client.force_authenticate(basic_user)

        response = self.client.post(path, data)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        # Moderator
        mod = create_random_authenticated_user("mod", moderator=True)
        self.client.force_authenticate(mod)
        response = self.client.post(path, data)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        with self.assertRaises(HubV2.DoesNotExist):
            HubV2.objects.get(id=hub_id)

    def test_cannot_edit_hub(self):
        hub = create_hub_v2(name="some hub")
        path = f"/api/hubs/{hub.id}/"
        data = {
            "id": hub.id,
            "display_name": "updated name",
            "description": "description",
        }

        # Unauthenticated
        response = self.client.put(path, data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Basic user
        basic_user = create_random_authenticated_user("basic_user")
        self.client.force_authenticate(basic_user)

        response = self.client.put(path, data)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        # Moderator
        mod = create_random_authenticated_user("mod", moderator=True)
        self.client.force_authenticate(mod)
        response = self.client.put(path, data)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        actual = HubV2.objects.get(id=hub.id)
        self.assertEqual(actual, hub)

    def test_cannot_partially_edit_hub(self):
        hub = create_hub_v2(name="some hub")
        path = f"/api/hubs/{hub.id}/"
        data = {
            "display_name": "updated name",
        }

        # Unauthenticated
        response = self.client.patch(path, data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Basic user
        basic_user = create_random_authenticated_user("basic_user")
        self.client.force_authenticate(basic_user)

        response = self.client.patch(path, data)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        # Moderator
        mod = create_random_authenticated_user("mod", moderator=True)
        self.client.force_authenticate(mod)
        response = self.client.patch(path, data)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        actual = HubV2.objects.get(id=hub.id)
        self.assertEqual(actual, hub)

    def test_cannot_delete_hub(self):
        hub = create_hub_v2(name="some hub")
        path = f"/api/hubs/{hub.id}/"

        # Unauthenticated
        response = self.client.delete(path)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Basic user
        basic_user = create_random_authenticated_user("basic_user")
        self.client.force_authenticate(basic_user)

        response = self.client.delete(path)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        # Moderator
        mod = create_random_authenticated_user("mod", moderator=True)
        self.client.force_authenticate(mod)
        response = self.client.delete(path)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        actual = HubV2.objects.get(id=hub.id)
        self.assertEqual(actual, hub)

    def test_get_existing_hub_succeeds(self):
        hub = create_hub_v2(name="some hub")
        path = f"/api/hubs/{hub.id}/"

        response = self.client.get(path)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        expected = {
            "id": hub.id,
            "display_name": hub.display_name,
            "description": hub.description,
        }
        self.assertEqual(response.data, expected)

    def test_get_non_existing_hub_not_found(self):
        response = self.client.get("/api/hubs/some-hub/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_hubs_succeeds(self):
        hubs = [create_hub_v2(name=f"hub {i}") for i in range(10)]

        response = self.client.get("/api/hubs/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        expected = {
            "count": len(hubs),
            "next": None,
            "previous": None,
            "results": [
                {
                    "id": hub.id,
                    "display_name": hub.display_name,
                    "description": hub.description,
                }
                for hub in hubs
            ],
        }
        self.assertEqual(response.json(), expected)

    def test_list_paginated_hubs_succeeds(self):
        nhubs = 10
        hubs = [create_hub_v2(name=f"hub {i}") for i in range(nhubs)]

        page_size = 3
        npages = ceil(nhubs / page_size)
        for p in range(npages):
            response = self.client.get(f"/api/hubs/?page={p+1}&page_size={page_size}")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            previous_page = "" if p <= 1 else f"page={p}&"
            expected = {
                "count": len(hubs),
                "next": None
                if p >= npages - 1
                else f"http://testserver/api/hubs/?page={p+2}&page_size={page_size}",
                "previous": None
                if p < 1
                else f"http://testserver/api/hubs/?{previous_page}page_size={page_size}",
                "results": [
                    {
                        "id": hub.id,
                        "display_name": hub.display_name,
                        "description": hub.description,
                    }
                    for hub in hubs[p * page_size : (p + 1) * page_size]
                ],
            }
            self.assertEqual(response.json(), expected)
