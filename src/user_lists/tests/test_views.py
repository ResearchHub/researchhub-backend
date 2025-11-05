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

    def test_create_list(self):
        response = self.client.post("/api/user_list/", {"name": "My List"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "My List")
        self.assertTrue(List.objects.filter(name="My List", created_by=self.user).exists())

    def test_create_list_duplicate_name(self):
        List.objects.create(name="My List", created_by=self.user)
        response = self.client.post("/api/user_list/", {"name": "My List"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_lists(self):
        List.objects.create(name="List 1", created_by=self.user)
        List.objects.create(name="List 2", created_by=self.user)
        response = self.client.get("/api/user_list/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 2)

    def test_list_other_user_lists(self):
        List.objects.create(name="Other List", created_by=self.other_user)
        response = self.client.get("/api/user_list/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data.get("results", response.data)), 0)

    def test_retrieve_list(self):
        list_obj = List.objects.create(name="My List", created_by=self.user)
        response = self.client.get(f"/api/user_list/{list_obj.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "My List")
        self.assertIn("items", response.data)
        self.assertIn("items_count", response.data)

    def test_retrieve_list_with_items(self):
        list_obj = List.objects.create(name="My List", created_by=self.user)
        doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        ListItem.objects.create(parent_list=list_obj, unified_document=doc, created_by=self.user)
        response = self.client.get(f"/api/user_list/{list_obj.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["items_count"], 1)
        self.assertEqual(len(response.data["items"]), 1)

    def test_update_list(self):
        list_obj = List.objects.create(name="My List", created_by=self.user)
        original_updated_date = list_obj.updated_date
        response = self.client.patch(f"/api/user_list/{list_obj.id}/", {"name": "Updated List"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Updated List")
        list_obj.refresh_from_db()
        self.assertEqual(list_obj.name, "Updated List")
        self.assertGreater(list_obj.updated_date, original_updated_date)

    def test_update_list_duplicate_name(self):
        List.objects.create(name="Existing List", created_by=self.user)
        list_obj = List.objects.create(name="My List", created_by=self.user)
        response = self.client.patch(f"/api/user_list/{list_obj.id}/", {"name": "Existing List"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)
        self.assertIn("already exists", str(response.data["error"]))

    def test_update_other_user_list(self):
        """Test that users cannot update other users' lists"""
        list_obj = List.objects.create(name="Other List", created_by=self.other_user)
        response = self.client.patch(f"/api/user_list/{list_obj.id}/", {"name": "Hacked"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_list(self):
        list_obj = List.objects.create(name="My List", created_by=self.user)
        response = self.client.delete(f"/api/user_list/{list_obj.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["success"], True)
        list_obj.refresh_from_db()
        self.assertTrue(list_obj.is_removed)

    def test_delete_list_removes_items(self):
        list_obj = List.objects.create(name="My List", created_by=self.user)
        doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        item = ListItem.objects.create(parent_list=list_obj, unified_document=doc, created_by=self.user)
        self.client.delete(f"/api/user_list/{list_obj.id}/")
        item.refresh_from_db()
        self.assertTrue(item.is_removed)

    def test_unauthenticated_access(self):
        self.client.force_authenticate(user=None)
        response = self.client.get("/api/user_list/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_pagination(self):
        """Test that lists are paginated with 20 items per page"""
        for i in range(25):
            List.objects.create(name=f"List {i}", created_by=self.user)
        response = self.client.get("/api/user_list/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data)
        self.assertEqual(len(response.data["results"]), 20)
        self.assertIsNotNone(response.data.get("next"))
        self.assertIsNone(response.data.get("previous"))

    def test_list_pagination_page_2(self):
        """Test pagination second page"""
        for i in range(25):
            List.objects.create(name=f"List {i}", created_by=self.user)
        response = self.client.get("/api/user_list/?page=2")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 5)
        self.assertIsNone(response.data.get("next"))
        self.assertIsNotNone(response.data.get("previous"))

    def test_list_sorting_by_updated_date(self):
        """Test that lists are sorted by updated_date descending"""
        list1 = List.objects.create(name="List 1", created_by=self.user)
        list2 = List.objects.create(name="List 2", created_by=self.user)
        response = self.client.get("/api/user_list/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertEqual(results[0]["id"], list2.id)
        self.assertEqual(results[1]["id"], list1.id)

    def test_retrieve_list_includes_created_by(self):
        """Test that retrieve endpoint includes created_by field"""
        list_obj = List.objects.create(name="My List", created_by=self.user)
        response = self.client.get(f"/api/user_list/{list_obj.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("created_by", response.data)
        self.assertEqual(response.data["created_by"], self.user.id)

    def test_retrieve_other_user_list(self):
        """Test that users can retrieve other users' lists (sharing)"""
        list_obj = List.objects.create(name="Other List", created_by=self.other_user)
        response = self.client.get(f"/api/user_list/{list_obj.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Other List")
        self.assertEqual(response.data["created_by"], self.other_user.id)

    def test_update_list_error_format(self):
        """Test that duplicate name error returns correct format"""
        List.objects.create(name="Existing List", created_by=self.user)
        list_obj = List.objects.create(name="My List", created_by=self.user)
        response = self.client.patch(f"/api/user_list/{list_obj.id}/", {"name": "Existing List"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_user_check_endpoint(self):
        """Test the user_check endpoint returns user's lists with items"""
        list1 = List.objects.create(name="List 1", created_by=self.user)
        list2 = List.objects.create(name="List 2", created_by=self.user)
        doc1 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        doc2 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        ListItem.objects.create(parent_list=list1, unified_document=doc1, created_by=self.user)
        ListItem.objects.create(parent_list=list2, unified_document=doc2, created_by=self.user)
        response = self.client.get("/api/user_list/user_check/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("lists", response.data)
        self.assertEqual(len(response.data["lists"]), 2)
        self.assertEqual(response.data["lists"][0]["id"], list2.id)
        self.assertEqual(response.data["lists"][0]["created_by"], self.user.id)
        self.assertEqual(len(response.data["lists"][0]["items"]), 1)

    def test_user_check_only_returns_user_lists(self):
        """Test that user_check only returns lists created by the user"""
        List.objects.create(name="My List", created_by=self.user)
        List.objects.create(name="Other List", created_by=self.other_user)
        response = self.client.get("/api/user_list/user_check/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["lists"]), 1)
        self.assertEqual(response.data["lists"][0]["name"], "My List")


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

    def test_create_list_item(self):
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

    def test_create_list_item_other_user_list(self):
        response = self.client.post(
            "/api/user_list_item/", {"parent_list": self.other_list.id, "unified_document": self.doc.id}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_items(self):
        ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.get("/api/user_list_item/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data.get("results", response.data)), 1)

    def test_list_items_filtered_by_parent_list(self):
        ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.get(f"/api/user_list_item/?parent_list={self.list_obj.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data.get("results", response.data)), 1)

    def test_retrieve_list_item(self):
        item = ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.get(f"/api/user_list_item/{item.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("unified_document_data", response.data)

    def test_delete_list_item(self):
        item = ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.delete(f"/api/user_list_item/{item.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["success"], True)
        item.refresh_from_db()
        self.assertTrue(item.is_removed)

    def test_add_item_to_list_action(self):
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

    def test_add_item_to_list_duplicate(self):
        ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.post(
            "/api/user_list_item/add-item-to-list/",
            {"parent_list": self.list_obj.id, "unified_document": self.doc.id},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_remove_item_from_list_action(self):
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

    def test_remove_item_from_list_not_found(self):
        response = self.client.post(
            "/api/user_list_item/remove-item-from-list/",
            {"parent_list": self.list_obj.id, "unified_document": self.doc.id},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_list_item(self):
        item = ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        new_list = List.objects.create(name="New List", created_by=self.user)
        original_updated_date = new_list.updated_date
        response = self.client.patch(f"/api/user_list_item/{item.id}/", {"parent_list": new_list.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item.refresh_from_db()
        self.assertEqual(item.parent_list, new_list)
        self._assert_updated_date_changed(new_list, original_updated_date)

    def test_update_list_item_other_user_list(self):
        item = ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.patch(f"/api/user_list_item/{item.id}/", {"parent_list": self.other_list.id})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("parent_list", response.data)
        item.refresh_from_db()
        self.assertEqual(item.parent_list, self.list_obj)

    def test_update_list_item_duplicate(self):
        other_doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        item1 = ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        item2 = ListItem.objects.create(parent_list=self.list_obj, unified_document=other_doc, created_by=self.user)
        response = self.client.patch(f"/api/user_list_item/{item2.id}/", {"unified_document": self.doc.id})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_create_list_item_duplicate_integrity_error(self):
        ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.post(
            "/api/user_list_item/", {"parent_list": self.list_obj.id, "unified_document": self.doc.id}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_unauthenticated_access(self):
        self.client.force_authenticate(user=None)
        response = self.client.get("/api/user_list_item/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_items_pagination(self):
        """Test that list items are paginated with 20 items per page"""
        for i in range(25):
            doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
            ListItem.objects.create(parent_list=self.list_obj, unified_document=doc, created_by=self.user)
        response = self.client.get("/api/user_list_item/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data)
        self.assertEqual(len(response.data["results"]), 20)
        self.assertIsNotNone(response.data.get("next"))
        self.assertIsNone(response.data.get("previous"))

    def test_list_items_sorting_by_created_date(self):
        """Test that list items are sorted by created_date descending"""
        doc1 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        doc2 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        item1 = ListItem.objects.create(parent_list=self.list_obj, unified_document=doc1, created_by=self.user)
        item2 = ListItem.objects.create(parent_list=self.list_obj, unified_document=doc2, created_by=self.user)
        response = self.client.get(f"/api/user_list_item/?parent_list={self.list_obj.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertEqual(results[0]["id"], item2.id)
        self.assertEqual(results[1]["id"], item1.id)

    def test_list_items_from_other_user_list(self):
        """Test that users can view items from other users' lists"""
        doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        ListItem.objects.create(parent_list=self.other_list, unified_document=doc, created_by=self.other_user)
        response = self.client.get(f"/api/user_list_item/?parent_list={self.other_list.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 1)

    def test_retrieve_item_from_other_user_list(self):
        """Test that users can retrieve items from other users' lists"""
        doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        item = ListItem.objects.create(parent_list=self.other_list, unified_document=doc, created_by=self.other_user)
        response = self.client.get(f"/api/user_list_item/{item.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("unified_document_data", response.data)

    def test_update_list_item_updates_both_parent_timestamps(self):
        """Test that moving an item updates both old and new parent timestamps"""
        new_list = List.objects.create(name="New List", created_by=self.user)
        item = ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        original_old_date = self.list_obj.updated_date
        original_new_date = new_list.updated_date
        response = self.client.patch(f"/api/user_list_item/{item.id}/", {"parent_list": new_list.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.list_obj.refresh_from_db()
        new_list.refresh_from_db()
        self.assertGreater(self.list_obj.updated_date, original_old_date)
        self.assertGreater(new_list.updated_date, original_new_date)

    def test_add_item_to_list_error_format(self):
        """Test that duplicate item error returns correct format with item data"""
        ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.post(
            "/api/user_list_item/add-item-to-list/",
            {"parent_list": self.list_obj.id, "unified_document": self.doc.id},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)
        self.assertIn("item", response.data)
        self.assertEqual(response.data["error"], "Item already in list")
