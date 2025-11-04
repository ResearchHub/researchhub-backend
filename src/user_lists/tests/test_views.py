from rest_framework import status
from rest_framework.test import APITestCase

from user.tests.helpers import create_random_authenticated_user

from user_lists.models import List


class ListViewSetTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("user1")
        self.client.force_authenticate(user=self.user)

    def test_create_list(self):
        response = self.client.post("/api/user_list/", {"name": "My List"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "My List")
        self.assertTrue(List.objects.filter(name="My List", created_by=self.user).exists())

    def test_create_list_with_is_public(self):
        response = self.client.post("/api/user_list/", {"name": "Public List", "is_public": True})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "Public List")
        self.assertTrue(response.data["is_public"])
        list_obj = List.objects.get(name="Public List", created_by=self.user)
        self.assertTrue(list_obj.is_public)

    def test_create_list_duplicate_name(self):
        List.objects.create(name="My List", created_by=self.user)
        response = self.client.post("/api/user_list/", {"name": "My List"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", response.data)

    def test_create_list_unauthenticated(self):
        self.client.force_authenticate(user=None)
        response = self.client.post("/api/user_list/", {"name": "My List"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_list_missing_name(self):
        response = self.client.post("/api/user_list/", {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

