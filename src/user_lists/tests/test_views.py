from rest_framework import status
from rest_framework.test import APITestCase

from researchhub_document.related_models.constants.document_type import PAPER
from researchhub_document.related_models.researchhub_unified_document_model import ResearchhubUnifiedDocument
from user.related_models.user_model import User
from user_lists.models import List, ListItem


class ListViewSetTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user1")
        self.other_user = User.objects.create_user(username="user2")
        self.client.force_authenticate(user=self.user)

    def test_user_can_create_list(self):
        response = self.client.post("/api/user_list/", {"name": "My List"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "My List")
        self.assertTrue(List.objects.filter(name="My List", created_by=self.user).exists())


    def test_user_can_create_public_list(self):
        response = self.client.post("/api/user_list/", {"name": "Public List", "is_public": True})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "Public List")
        self.assertTrue(response.data["is_public"])
        list_obj = List.objects.get(name="Public List", created_by=self.user)
        self.assertTrue(list_obj.is_public)

    def test_user_can_create_list_with_duplicate_name(self):
        # Users can create multiple lists with the same name
        List.objects.create(name="My List", created_by=self.user)
        response = self.client.post("/api/user_list/", {"name": "My List"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "My List")
        # Verify both lists exist
        self.assertEqual(List.objects.filter(name="My List", created_by=self.user).count(), 2)

    def test_unauthorized_user_cannot_create_list(self):
        self.client.force_authenticate(user=None)
        response = self.client.post("/api/user_list/", {"name": "My List"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_user_cannot_create_list_without_name(self):
        response = self.client.post("/api/user_list/", {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)
        self.assertIsInstance(response.data["error"], str)

    def test_user_can_update_list(self):
        list_obj = List.objects.create(name="My List", created_by=self.user)
        original_updated_date = list_obj.updated_date
        response = self.client.patch(f"/api/user_list/{list_obj.id}/", {"name": "Updated List"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Updated List")
        list_obj.refresh_from_db()
        self.assertEqual(list_obj.name, "Updated List")
        self.assertGreater(list_obj.updated_date, original_updated_date)

    def test_user_cannot_update_other_user_list(self):
        list_obj = List.objects.create(name="Other List", created_by=self.other_user)
        response = self.client.patch(f"/api/user_list/{list_obj.id}/", {"name": "Hacked"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_user_can_delete_list(self):
        list_obj = List.objects.create(name="My List", created_by=self.user)
        response = self.client.delete(f"/api/user_list/{list_obj.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["success"], True)
        list_obj = List.all_objects.get(pk=list_obj.pk)
        self.assertTrue(list_obj.is_removed)


    def test_deleting_list_removes_all_items(self):
       
        list_obj = List.objects.create(name="My List", created_by=self.user)
        doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        item = ListItem.objects.create(parent_list=list_obj, unified_document=doc, created_by=self.user)
        self.client.delete(f"/api/user_list/{list_obj.id}/")
        item = ListItem.all_objects.get(pk=item.pk)
        self.assertTrue(item.is_removed)

    def test_unauthenticated_access(self):
        self.client.force_authenticate(user=None)
        response = self.client.get("/api/user_list/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ListItemViewSetTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user1")
        self.other_user = User.objects.create_user(username="user2")
        self.list_obj = List.objects.create(name="My List", created_by=self.user)
        self.other_list = List.objects.create(name="Other List", created_by=self.other_user)
        self.doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        self.client.force_authenticate(user=self.user)

    def _assert_updated_date_changed(self, list_obj, original_date):
        list_obj.refresh_from_db()
        self.assertGreater(list_obj.updated_date, original_date)

    def test_user_can_create_list_item(self):
        original_updated_date = self.list_obj.updated_date
        response = self.client.post(
            "/api/user_list_item/", {"parent_list": self.list_obj.id, "unified_document": self.doc.id}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            ListItem.objects.filter(
                parent_list=self.list_obj, unified_document=self.doc, created_by=self.user
            ).exists()
        )
        self._assert_updated_date_changed(self.list_obj, original_updated_date)

    def test_user_cannot_create_item_in_other_user_list(self):
        response = self.client.post(
            "/api/user_list_item/", {"parent_list": self.other_list.id, "unified_document": self.doc.id}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_user_can_list_items(self):
        ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.get("/api/user_list_item/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data.get("results", response.data)), 1)

    def test_user_can_filter_items_by_parent_list(self):
        ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.get(f"/api/user_list_item/?parent_list={self.list_obj.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data.get("results", response.data)), 1)

    def test_user_can_retrieve_list_item(self):
        item = ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.get(f"/api/user_list_item/{item.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("unified_document_data", response.data)

    def test_user_can_delete_list_item(self):
        item = ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.delete(f"/api/user_list_item/{item.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["success"], True)
        item.refresh_from_db()
        self.assertTrue(item.is_removed)

    def test_user_can_add_item_to_list(self):
        original_updated_date = self.list_obj.updated_date
        response = self.client.post(
            "/api/user_list_item/add-item-to-list/",
            {"parent_list": self.list_obj.id, "unified_document": self.doc.id},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            "unified_document_data" in response.data
            or response.data.get("success") == True
            or "id" in response.data
        )
        self._assert_updated_date_changed(self.list_obj, original_updated_date)

    def test_user_cannot_add_duplicate_item_to_list(self):
        ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.post(
            "/api/user_list_item/add-item-to-list/",
            {"parent_list": self.list_obj.id, "unified_document": self.doc.id},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_user_can_remove_item_from_list(self):
        ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        original_updated_date = self.list_obj.updated_date
        response = self.client.post(
            "/api/user_list_item/remove-item-from-list/",
            {"parent_list": self.list_obj.id, "unified_document": self.doc.id},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertFalse(
            ListItem.objects.filter(
                parent_list=self.list_obj, unified_document=self.doc, is_removed=False
            ).exists()
        )
        self._assert_updated_date_changed(self.list_obj, original_updated_date)

    def test_user_cannot_remove_item_that_does_not_exist(self):
        response = self.client.post(
            "/api/user_list_item/remove-item-from-list/",
            {"parent_list": self.list_obj.id, "unified_document": self.doc.id},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_user_can_update_list_item(self):
        item = ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        new_list = List.objects.create(name="New List", created_by=self.user)
        original_updated_date = new_list.updated_date
        response = self.client.patch(f"/api/user_list_item/{item.id}/", {"parent_list": new_list.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item.refresh_from_db()
        self.assertEqual(item.parent_list, new_list)
        self._assert_updated_date_changed(new_list, original_updated_date)

    def test_user_cannot_update_item_to_other_user_list(self):
        item = ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.patch(f"/api/user_list_item/{item.id}/", {"parent_list": self.other_list.id})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("parent_list", response.data)
        item.refresh_from_db()
        self.assertEqual(item.parent_list, self.list_obj)

    def test_user_cannot_update_item_to_duplicate(self):
        other_doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        item2 = ListItem.objects.create(parent_list=self.list_obj, unified_document=other_doc, created_by=self.user)
        response = self.client.patch(f"/api/user_list_item/{item2.id}/", {"unified_document": self.doc.id})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_user_cannot_create_duplicate_item(self):
        ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.post(
            "/api/user_list_item/", {"parent_list": self.list_obj.id, "unified_document": self.doc.id}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_unauthenticated_user_cannot_access_items(self):
        self.client.force_authenticate(user=None)
        response = self.client.get("/api/user_list_item/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
