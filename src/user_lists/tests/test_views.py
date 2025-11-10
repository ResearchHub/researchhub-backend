from django.db import IntegrityError
from django.utils import timezone
from rest_framework import status
from rest_framework.serializers import ValidationError
from rest_framework.test import APITestCase

from researchhub_document.related_models.constants.document_type import PAPER
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_authenticated_user

from user_lists.models import List, ListItem


class ListViewSetTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("user1")
        self.other_user = create_random_authenticated_user("user2")
        self.client.force_authenticate(user=self.user)

    def test_user_can_create_list(self):
        response = self.client.post("/api/user_list/", {"name": "My List"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "My List")

    def test_creating_list_with_empty_name_shows_formatted_error(self):
        response = self.client.post("/api/user_list/", {"name": ""})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)
        self.assertIn("name", response.data["error"].lower())

    def test_creating_list_with_missing_name_shows_formatted_error(self):
        response = self.client.post("/api/user_list/", {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)
        self.assertIn("name", response.data["error"].lower())

    def test_user_can_only_access_their_own_lists(self):
        my_list = List.objects.create(name="My List", created_by=self.user)
        other_list = List.objects.create(name="Other List", created_by=self.other_user)
        response = self.client.patch(f"/api/user_list/{my_list.id}/", {"name": "Updated"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response = self.client.patch(f"/api/user_list/{other_list.id}/", {"name": "Hacked"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_updating_list_updates_timestamp(self):
        list_obj = List.objects.create(name="My List", created_by=self.user)
        original_date = list_obj.updated_date
        response = self.client.patch(f"/api/user_list/{list_obj.id}/", {"name": "Updated"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        list_obj.refresh_from_db()
        self.assertGreater(list_obj.updated_date, original_date)
        self.assertEqual(list_obj.updated_by, self.user)

    def test_deleting_list_also_deletes_all_items(self):
        list_obj = List.objects.create(name="My List", created_by=self.user)
        item1 = ListItem.objects.create(
            parent_list=list_obj,
            unified_document=ResearchhubUnifiedDocument.objects.create(document_type=PAPER),
            created_by=self.user,
        )
        item2 = ListItem.objects.create(
            parent_list=list_obj,
            unified_document=ResearchhubUnifiedDocument.objects.create(document_type=PAPER),
            created_by=self.user,
        )
        item2.delete()
        item2_id = item2.id
        item1_id = item1.id
        response = self.client.delete(f"/api/user_list/{list_obj.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(List.objects.filter(id=list_obj.id).exists())
        self.assertFalse(ListItem.objects.filter(id=item1.id, is_removed=False).exists())
        self.assertTrue(ListItem.all_objects.filter(id=item2_id, is_removed=True).exists())
        item1_deleted = ListItem.all_objects.get(id=item1_id)
        self.assertTrue(item1_deleted.is_removed)
        self.assertIsNotNone(item1_deleted.is_removed_date)

    def test_user_can_list_their_own_lists(self):
        List.objects.create(name="List 1", created_by=self.user)
        List.objects.create(name="List 2", created_by=self.user)
        List.objects.create(name="Other List", created_by=self.other_user)
        response = self.client.get("/api/user_list/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)
        list_names = [list_data["name"] for list_data in response.data["results"]]
        self.assertIn("List 1", list_names)
        self.assertIn("List 2", list_names)
        self.assertNotIn("Other List", list_names)

    def test_user_can_retrieve_their_own_list(self):
        list_obj = List.objects.create(name="My List", created_by=self.user)
        response = self.client.get(f"/api/user_list/{list_obj.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "My List")
        self.assertEqual(response.data["id"], list_obj.id)

    def test_user_cannot_retrieve_other_user_list(self):
        other_list = List.objects.create(name="Other List", created_by=self.other_user)
        response = self.client.get(f"/api/user_list/{other_list.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ListItemViewSetTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("user1")
        self.other_user = create_random_authenticated_user("user2")
        self.client.force_authenticate(user=self.user)
        self.list_obj = List.objects.create(name="My List", created_by=self.user)
        self.other_list = List.objects.create(name="Other List", created_by=self.other_user)
        self.doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)

    def test_user_can_only_see_their_own_items(self):
        ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        ListItem.objects.create(parent_list=self.other_list, unified_document=self.doc, created_by=self.other_user)
        response = self.client.get("/api/user_list_item/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

    def test_filtering_items_by_parent_list_returns_only_items_from_that_list(self):
        other_doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        ListItem.objects.create(parent_list=self.list_obj, unified_document=other_doc, created_by=self.user)
        other_list = List.objects.create(name="Other", created_by=self.user)
        ListItem.objects.create(parent_list=other_list, unified_document=self.doc, created_by=self.user)
        response = self.client.get(f"/api/user_list_item/?parent_list={self.list_obj.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)

    def test_filtering_items_by_removed_parent_list_returns_empty(self):
        removed_list = List.objects.create(name="Removed", created_by=self.user)
        ListItem.objects.create(parent_list=removed_list, unified_document=self.doc, created_by=self.user)
        removed_list.delete()
        response = self.client.get(f"/api/user_list_item/?parent_list={removed_list.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

    def test_filtering_items_by_other_user_parent_list_returns_empty(self):
        response = self.client.get(f"/api/user_list_item/?parent_list={self.other_list.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

    def test_retrieving_item_uses_detail_serializer(self):
        item = ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.get(f"/api/user_list_item/{item.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("unified_document_data", response.data)

    def test_listing_items_uses_detail_serializer(self):
        ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.get("/api/user_list_item/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        if len(response.data["results"]) > 0:
            self.assertIn("unified_document_data", response.data["results"][0])

    def test_creating_item_uses_basic_serializer(self):
        response = self.client.post("/api/user_list_item/", {"parent_list": self.list_obj.id, "unified_document": self.doc.id})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn("unified_document_data", response.data)

    def test_updating_item_uses_basic_serializer(self):
        item = ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.patch(f"/api/user_list_item/{item.id}/", {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("unified_document_data", response.data)

    def test_user_cannot_create_item_in_other_user_list(self):
        response = self.client.post("/api/user_list_item/", {"parent_list": self.other_list.id, "unified_document": self.doc.id})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("parent_list", response.data)

    def test_user_cannot_create_item_in_removed_list(self):
        self.list_obj.delete()
        response = self.client.post("/api/user_list_item/", {"parent_list": self.list_obj.id, "unified_document": self.doc.id})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("parent_list", response.data)

    def test_creating_item_updates_parent_list_timestamp(self):
        response = self.client.post("/api/user_list_item/", {"parent_list": self.list_obj.id, "unified_document": self.doc.id})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.list_obj.refresh_from_db()
        self.assertEqual(self.list_obj.updated_by, self.user)

    def test_creating_duplicate_item_shows_error(self):
        ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.post("/api/user_list_item/", {"parent_list": self.list_obj.id, "unified_document": self.doc.id})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Item already exists in this list.")

    def test_updating_item_to_different_list_updates_both_timestamps(self):
        item = ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        new_list = List.objects.create(name="New List", created_by=self.user)
        original_date = self.list_obj.updated_date
        new_list_original_date = new_list.updated_date
        response = self.client.patch(f"/api/user_list_item/{item.id}/", {"parent_list": new_list.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.list_obj.refresh_from_db()
        new_list.refresh_from_db()
        self.assertGreater(self.list_obj.updated_date, original_date)
        self.assertEqual(self.list_obj.updated_by, self.user)
        self.assertGreater(new_list.updated_date, new_list_original_date)
        self.assertEqual(new_list.updated_by, self.user)

    def test_updating_item_without_changing_list_still_updates_timestamp(self):
        item = ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.patch(f"/api/user_list_item/{item.id}/", {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.list_obj.refresh_from_db()
        self.assertEqual(self.list_obj.updated_by, self.user)

    def test_updating_item_to_duplicate_shows_error(self):
        other_doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        item = ListItem.objects.create(parent_list=self.list_obj, unified_document=other_doc, created_by=self.user)
        ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.patch(f"/api/user_list_item/{item.id}/", {"unified_document": self.doc.id})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Item already exists in this list.")

    def test_deleting_item_updates_parent_list_timestamp(self):
        item = ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.delete(f"/api/user_list_item/{item.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.list_obj.refresh_from_db()
        self.assertEqual(self.list_obj.updated_by, self.user)

    def test_adding_existing_item_to_list_shows_error_with_item_details(self):
        item = ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.post(
            "/api/user_list_item/add-item-to-list/",
            {"parent_list": self.list_obj.id, "unified_document": self.doc.id},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Item already in list")
        self.assertIn("item", response.data)
        self.assertEqual(response.data["item"]["id"], item.id)

    def test_adding_item_ignores_already_removed_items(self):
        item = ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        item.delete()
        response = self.client.post(
            "/api/user_list_item/add-item-to-list/",
            {"parent_list": self.list_obj.id, "unified_document": self.doc.id},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_adding_new_item_to_list_returns_created_response(self):
        other_doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        response = self.client.post(
            "/api/user_list_item/add-item-to-list/",
            {"parent_list": self.list_obj.id, "unified_document": other_doc.id},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("id", response.data)

    def test_adding_duplicate_item_through_add_action_shows_error(self):
        ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.post(
            "/api/user_list_item/add-item-to-list/",
            {"parent_list": self.list_obj.id, "unified_document": self.doc.id},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Item already in list")

    def test_removing_item_from_list_returns_success(self):
        item = ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.post(
            "/api/user_list_item/remove-item-from-list/",
            {"parent_list": self.list_obj.id, "unified_document": self.doc.id},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(ListItem.objects.filter(id=item.id, is_removed=False).exists())
        self.list_obj.refresh_from_db()
        self.assertEqual(self.list_obj.updated_by, self.user)

    def test_removing_nonexistent_item_shows_not_found_error(self):
        response = self.client.post(
            "/api/user_list_item/remove-item-from-list/",
            {"parent_list": self.list_obj.id, "unified_document": self.doc.id},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_removing_item_created_by_different_user_shows_not_found_error(self):
        ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.other_user)
        response = self.client.post(
            "/api/user_list_item/remove-item-from-list/",
            {"parent_list": self.list_obj.id, "unified_document": self.doc.id},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


    def test_serialize_item_returns_data(self):
        item = ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.get(f"/api/user_list_item/{item.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("id", response.data)
        self.assertIn("unified_document_data", response.data)

    def test_update_list_timestamp_updates_fields(self):
        list_obj = List.objects.create(name="Test List", created_by=self.user)
        original_date = list_obj.updated_date
        
        response = self.client.patch(f"/api/user_list/{list_obj.id}/", {"name": "Updated Name"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        list_obj.refresh_from_db()
        
        self.assertGreater(list_obj.updated_date, original_date)
        self.assertEqual(list_obj.updated_by, self.user)

    def test_handle_integrity_error_item_raises_validation_error(self):
        ListItem.objects.create(parent_list=self.list_obj, unified_document=self.doc, created_by=self.user)
        response = self.client.post("/api/user_list_item/", {"parent_list": self.list_obj.id, "unified_document": self.doc.id})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Item already exists in this list.")

    def test_validate_parent_list_rejects_other_user_list(self):
        response = self.client.post("/api/user_list_item/", {"parent_list": self.other_list.id, "unified_document": self.doc.id})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("parent_list", response.data)

    def test_validate_parent_list_rejects_removed_list(self):
        removed_list = List.objects.create(name="Removed List", created_by=self.user)
        removed_list.delete()
        
        response = self.client.post("/api/user_list_item/", {"parent_list": removed_list.id, "unified_document": self.doc.id})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("parent_list", response.data)

    def test_validate_parent_list_accepts_valid_list(self):
        response = self.client.post("/api/user_list_item/", {"parent_list": self.list_obj.id, "unified_document": self.doc.id})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_remove_item_from_list_with_invalid_parent_list(self):
        response = self.client.post(
            "/api/user_list_item/remove-item-from-list/",
            {"parent_list": 99999, "unified_document": self.doc.id},
        )
        self.assertIn(response.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND])

    def test_remove_item_from_list_with_invalid_document(self):
        response = self.client.post(
            "/api/user_list_item/remove-item-from-list/",
            {"parent_list": self.list_obj.id, "unified_document": 99999},
        )
        self.assertIn(response.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND])
