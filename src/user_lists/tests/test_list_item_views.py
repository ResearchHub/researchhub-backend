from rest_framework import status
from rest_framework.test import APITestCase

from researchhub_document.related_models.constants.document_type import PAPER
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_authenticated_user

from user_lists.models import List, ListItem


class ListItemViewSetTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("user1")
        self.other_user = create_random_authenticated_user("user2")
        self.client.force_authenticate(user=self.user)
        self.list = List.objects.create(name="My List", created_by=self.user)
        self.doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)

    def test_user_can_add_item_to_list(self):
        response = self.client.post("/api/user_list_item/", {
            "parent_list": self.list.id,
            "unified_document": self.doc.id,
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(ListItem.objects.filter(
            parent_list=self.list,
            unified_document=self.doc,
            created_by=self.user
        ).exists())

    def test_unauthenticated_user_cannot_add_item_to_list(self):
        self.client.force_authenticate(user=None)
        response = self.client.post("/api/user_list_item/", {
            "parent_list": self.list.id,
            "unified_document": self.doc.id,
        })
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_cannot_add_duplicate_item_to_list(self):
        ListItem.objects.create(parent_list=self.list, unified_document=self.doc, created_by=self.user)
        response = self.client.post("/api/user_list_item/", {
            "parent_list": self.list.id,
            "unified_document": self.doc.id,
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_add_item_to_another_users_list(self):
        other_list = List.objects.create(name="Other List", created_by=self.other_user)
        response = self.client.post("/api/user_list_item/", {
            "parent_list": other_list.id,
            "unified_document": self.doc.id,
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_add_item_to_deleted_list(self):
        self.list.is_removed = True
        self.list.save()
        response = self.client.post("/api/user_list_item/", {
            "parent_list": self.list.id,
            "unified_document": self.doc.id,
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_user_can_delete_item_from_their_list(self):
        item = ListItem.objects.create(parent_list=self.list, unified_document=self.doc, created_by=self.user)
        response = self.client.delete(f"/api/user_list_item/{item.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        item.refresh_from_db()
        self.assertTrue(item.is_removed)

    def test_user_cannot_delete_item_from_another_users_list(self):
        other_list = List.objects.create(name="Other List", created_by=self.other_user)
        item = ListItem.objects.create(parent_list=other_list, unified_document=self.doc, created_by=self.other_user)
        response = self.client.delete(f"/api/user_list_item/{item.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

