from rest_framework import status
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
        response = self.client.post("/api/lists/", {"name": "My List"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "My List")
        self.assertTrue(List.objects.filter(name="My List", created_by=self.user).exists())
    def test_user_can_create_multiple_lists_with_same_name(self):
        List.objects.create(name="My List", created_by=self.user)
        response = self.client.post("/api/lists/", {"name": "My List"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(List.objects.filter(name="My List", created_by=self.user).count(), 2)

    def test_unauthenticated_user_cannot_create_list(self):
        self.client.force_authenticate(user=None)
        response = self.client.post("/api/lists/", {"name": "My List"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_creating_list_without_name_returns_error(self):
        response = self.client.post("/api/lists/", {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_user_can_update_their_list(self):
        list_obj = List.objects.create(name="My List", created_by=self.user)
        response = self.client.patch(f"/api/lists/{list_obj.id}/", {"name": "Updated List"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        list_obj.refresh_from_db()
        self.assertEqual(list_obj.name, "Updated List")
        self.assertEqual(list_obj.updated_by, self.user)

    def test_user_cannot_update_another_users_list(self):
        list_obj = List.objects.create(name="Other List", created_by=self.other_user)
        response = self.client.patch(f"/api/lists/{list_obj.id}/", {"name": "Hacked"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
   
    def test_user_can_retrieve_their_lists(self):
        list1 = List.objects.create(name="List 1", created_by=self.user)
        list2 = List.objects.create(name="List 2", created_by=self.user)
        doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        ListItem.objects.create(parent_list=list1, unified_document=doc, created_by=self.user)
        
        response = self.client.get("/api/lists/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)
        
        list1_data = next(item for item in response.data["results"] if item["id"] == list1.id)
        self.assertEqual(list1_data["name"], "List 1")
        self.assertEqual(list1_data["item_count"], 1)
        
        list2_data = next(item for item in response.data["results"] if item["id"] == list2.id)
        self.assertEqual(list2_data["name"], "List 2")
        self.assertEqual(list2_data["item_count"], 0)

    def test_item_count_excludes_removed_items(self):
        list_obj = List.objects.create(name="My List", created_by=self.user)
        doc1 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        doc2 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        
        item1 = ListItem.objects.create(parent_list=list_obj, unified_document=doc1, created_by=self.user)
        ListItem.objects.create(parent_list=list_obj, unified_document=doc2, created_by=self.user)
        
        item1.is_removed = True
        item1.save()
        
        response = self.client.get(f"/api/lists/{list_obj.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["item_count"], 1)
        
    def test_user_can_delete_their_list(self):
        list_obj = List.objects.create(name="My List", created_by=self.user)
        response = self.client.delete(f"/api/lists/{list_obj.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        list_obj = List.all_objects.get(pk=list_obj.pk)
        self.assertTrue(list_obj.is_removed)

    def test_list_overview_returns_all_lists_with_documents(self):
        list1 = List.objects.create(name="List 1", created_by=self.user)
        list2 = List.objects.create(name="List 2", created_by=self.user)
        doc1 = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        doc2 = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        doc3 = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")

        ListItem.objects.create(parent_list=list1, unified_document=doc1, created_by=self.user)
        ListItem.objects.create(parent_list=list1, unified_document=doc2, created_by=self.user)
        ListItem.objects.create(parent_list=list2, unified_document=doc3, created_by=self.user)

        response = self.client.get("/api/lists/overview/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["lists"]), 2)

        list1_data = next(item for item in response.data["lists"] if item["list_id"] == list1.id)
        self.assertEqual(list1_data["name"], "List 1")
        self.assertEqual(len(list1_data["unified_documents"]), 2)
        list1_doc_ids = [item["unified_document_id"] for item in list1_data["unified_documents"]]
        self.assertIn(doc1.id, list1_doc_ids)
        self.assertIn(doc2.id, list1_doc_ids)

        list2_data = next(item for item in response.data["lists"] if item["list_id"] == list2.id)
        self.assertEqual(list2_data["name"], "List 2")
        self.assertEqual(len(list2_data["unified_documents"]), 1)
        list2_doc_ids = [item["unified_document_id"] for item in list2_data["unified_documents"]]
        self.assertIn(doc3.id, list2_doc_ids)

    def test_list_overview_excludes_removed_items(self):
        list_obj = List.objects.create(name="My List", created_by=self.user)
        doc1 = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        doc2 = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")

        item1 = ListItem.objects.create(parent_list=list_obj, unified_document=doc1, created_by=self.user)
        ListItem.objects.create(parent_list=list_obj, unified_document=doc2, created_by=self.user)

        item1.is_removed = True
        item1.save()

        response = self.client.get("/api/lists/overview/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        list_data = next(item for item in response.data["lists"] if item["list_id"] == list_obj.id)
        self.assertEqual(list_data["name"], "My List")
        self.assertEqual(len(list_data["unified_documents"]), 1)
        doc_ids = [item["unified_document_id"] for item in list_data["unified_documents"]]
        self.assertIn(doc2.id, doc_ids)
        self.assertNotIn(doc1.id, doc_ids)