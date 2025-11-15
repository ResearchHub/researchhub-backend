from rest_framework import status
from rest_framework.test import APITestCase

from researchhub_document.related_models.constants.document_type import PAPER
from researchhub_document.related_models.researchhub_unified_document_model import ResearchhubUnifiedDocument
from user.related_models.user_model import User
from user_lists.models import List, ListItem


class ListViewSetTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser")
        self.other_user = User.objects.create_user(username="otheruser")
        self.client.force_authenticate(self.user)

    def test_create_list(self):
        response = self.client.post("/api/user_list/", {"name": "Reading List"})
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "Reading List")
        self.assertEqual(response.data["created_by"], self.user.id)

    def test_update_list_and_timestamp(self):
        list_obj = List.objects.create(name="Old Name", created_by=self.user)
        
        response = self.client.patch(f"/api/user_list/{list_obj.id}/", {"name": "New Name"})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        list_obj.refresh_from_db()
        self.assertEqual(list_obj.name, "New Name")

    def test_delete_list_soft_deletes_list_only(self):
        list_obj = List.objects.create(name="My List", created_by=self.user)
        doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        item = ListItem.objects.create(parent_list=list_obj, unified_document=doc, created_by=self.user)
        
        response = self.client.delete(f"/api/user_list/{list_obj.id}/")
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertTrue(List.all_objects.get(pk=list_obj.pk).is_removed)
        self.assertFalse(ListItem.all_objects.get(pk=item.pk).is_removed)

    def test_cannot_access_other_users_list(self):
        other_list = List.objects.create(name="Private List", created_by=self.other_user)
        
        response = self.client.get(f"/api/user_list/{other_list.id}/")
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_overview_returns_lists_with_items(self):
        list_obj = List.objects.create(name="My List", created_by=self.user)
        doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        item = ListItem.objects.create(parent_list=list_obj, unified_document=doc, created_by=self.user)
        
        response = self.client.get("/api/user_list/overview/")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["lists"]), 1)
        self.assertEqual(response.data["lists"][0]["id"], list_obj.id)
        self.assertEqual(response.data["lists"][0]["items"][0]["id"], item.id)

    def test_requires_authentication(self):
        self.client.force_authenticate(None)
        
        response = self.client.get("/api/user_list/")
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ListItemViewSetTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser")
        self.other_user = User.objects.create_user(username="otheruser")
        self.client.force_authenticate(self.user)
        self.list = List.objects.create(name="My List", created_by=self.user)
        self.doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)

    def test_create_item_updates_list_timestamp(self):
        response = self.client.post("/api/user_list_item/", {
            "parent_list": self.list.id,
            "unified_document": self.doc.id
        })
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(ListItem.objects.filter(parent_list=self.list, unified_document=self.doc).exists())

    def test_cannot_create_duplicate_item(self):
        ListItem.objects.create(parent_list=self.list, unified_document=self.doc, created_by=self.user)
        
        response = self.client.post("/api/user_list_item/", {
            "parent_list": self.list.id,
            "unified_document": self.doc.id
        })
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_add_to_other_users_list(self):
        other_list = List.objects.create(name="Other List", created_by=self.other_user)
        
        response = self.client.post("/api/user_list_item/", {
            "parent_list": other_list.id,
            "unified_document": self.doc.id
        })
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_move_item_updates_both_lists_timestamps(self):
        item = ListItem.objects.create(parent_list=self.list, unified_document=self.doc, created_by=self.user)
        new_list = List.objects.create(name="New List", created_by=self.user)
        
        response = self.client.put(
            f"/api/user_list_item/{item.id}/",
            {"parent_list": new_list.id, "unified_document": self.doc.id},
            content_type="application/json"
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item.refresh_from_db()
        self.assertEqual(item.parent_list.id, new_list.id)

    def test_cannot_move_item_to_create_duplicate(self):
        new_list = List.objects.create(name="New List", created_by=self.user)
        item = ListItem.objects.create(parent_list=self.list, unified_document=self.doc, created_by=self.user)
        ListItem.objects.create(parent_list=new_list, unified_document=self.doc, created_by=self.user)
        
        response = self.client.put(
            f"/api/user_list_item/{item.id}/",
            {"parent_list": new_list.id, "unified_document": self.doc.id},
            content_type="application/json"
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_item_updates_list_timestamp(self):
        item = ListItem.objects.create(parent_list=self.list, unified_document=self.doc, created_by=self.user)
        
        response = self.client.delete(f"/api/user_list_item/{item.id}/")
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertTrue(ListItem.all_objects.get(pk=item.pk).is_removed)

    def test_filter_items_by_list(self):
        ListItem.objects.create(parent_list=self.list, unified_document=self.doc, created_by=self.user)
        
        response = self.client.get(f"/api/user_list_item/?parent_list={self.list.id}")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data.get("results", response.data)), 1)
