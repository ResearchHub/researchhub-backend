from rest_framework import status
from rest_framework.test import APITestCase

from paper.related_models.paper_model import Paper
from researchhub_document.related_models.constants.document_type import PAPER
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.related_models.user_model import User

from .models import UserSavedEntry, UserSavedList


class UserSavedViewTests(APITestCase):
    def setUp(self):
        # Create two users for testing user scoping
        self.user1 = User.objects.create_user(username="user1")
        self.user2 = User.objects.create_user(username="user2")

        # Create unified documents
        self.doc1 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        self.doc2 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        # create papers
        self.paper1 = Paper.objects.create(unified_document=self.doc1)
        self.paper2 = Paper.objects.create(unified_document=self.doc2)

        # Create lists for user1
        self.list1 = UserSavedList.objects.create(
            created_by=self.user1, list_name="list1"
        )
        self.list2 = UserSavedList.objects.create(
            created_by=self.user1, list_name="list2"
        )

        # Create a list for user2
        self.list3 = UserSavedList.objects.create(
            created_by=self.user2, list_name="list3"
        )

        # Add a document to list1
        UserSavedEntry.objects.create(
            created_by=self.user1, parent_list=self.list1, unified_document=self.doc1
        )

        # Add a document to list3
        UserSavedEntry.objects.create(
            created_by=self.user2, parent_list=self.list3, unified_document=self.doc1
        )

    def test_get_all_items_authenticated(self):
        """Test GET with all flag returns all user item counts"""
        # Add doc1 to list2 as well (it's already in list1 from setUp)
        UserSavedEntry.objects.create(
            created_by=self.user1, parent_list=self.list2, unified_document=self.doc1
        )

        # Add doc2 to list1
        UserSavedEntry.objects.create(
            created_by=self.user1, parent_list=self.list1, unified_document=self.doc2
        )

        # Add doc2 to list2 as well
        UserSavedEntry.objects.create(
            created_by=self.user1, parent_list=self.list2, unified_document=self.doc2
        )

        self.client.force_authenticate(user=self.user1)
        response = self.client.get("/user_saved/?all_items=true")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            {
                str(self.doc1.id): 2,  # doc1 appears in both lists
                str(self.doc2.id): 2,  # doc2 appears in both lists
            },
        )

    def test_get_all_lists_authenticated(self):
        """Test GET without list_name returns all user list names"""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get("/user_saved/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, ["list1", "list2"])

    def test_get_specific_list_items(self):
        """Test GET with list_name returns document details in the list"""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get("/user_saved/", {"list_name": "list1"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], self.doc1.id)
        self.assertIn("documents", response.data[0])
        self.assertIn("document_type", response.data[0])
        self.assertIn("hubs", response.data[0])

    def test_get_lists_by_u_doc_id(self):
        """Test GET with u_doc_id returns lists containing that document"""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get("/user_saved/", {"u_doc_id": self.doc1.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, ["list1"])

    def test_get_lists_by_paper_id(self):
        """Test GET with paper_id returns lists containing that paper"""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get("/user_saved/", {"paper_id": self.paper1.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, ["list1"])

    def test_get_nonexistent_list(self):
        """Test GET with nonexistent list_name returns not found error"""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get("/user_saved/", {"list_name": "nonexistent"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "List not found")

    def test_get_empty_list(self):
        """Test GET with empty list returns empty array"""
        self.client.force_authenticate(user=self.user1)
        response = self.client.get("/user_saved/", {"list_name": "list2"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_get_unauthenticated(self):
        """Test GET fails for unauthenticated user"""
        response = self.client.get("/user_saved/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_post_create_list(self):
        """Test POST creates a new list"""
        self.client.force_authenticate(user=self.user1)
        response = self.client.post("/user_saved/", {"list_name": "new_list"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"success": True, "list_name": "new_list"})
        self.assertTrue(
            UserSavedList.objects.filter(
                created_by=self.user1, list_name="new_list", is_removed=False
            ).exists()
        )

    def test_post_duplicate_list_name(self):
        """Test POST fails for duplicate list name"""
        self.client.force_authenticate(user=self.user1)
        response = self.client.post("/user_saved/", {"list_name": "list1"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "List name already exists")

    def test_post_invalid_data(self):
        """Test POST fails for invalid request body"""
        self.client.force_authenticate(user=self.user1)
        response = self.client.post("/user_saved/", {"list_name": ""})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_post_unauthenticated(self):
        """Test POST fails for unauthenticated user"""
        response = self.client.post("/user_saved/", {"list_name": "new_list"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_put_add_document_by_u_doc_id(self):
        """Test PUT adds a document to a list using u_doc_id"""
        self.client.force_authenticate(user=self.user1)
        response = self.client.put(
            "/user_saved/",
            {
                "list_name": "list2",
                "delete_flag": False,
                "u_doc_id": self.doc2.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            {
                "success": True,
                "list_name": "list2",
                "document_id": self.doc2.id,
                "delete_flag": False,
            },
        )
        self.assertTrue(
            UserSavedEntry.objects.filter(
                created_by=self.user1,
                parent_list=self.list2,
                unified_document=self.doc2,
                is_removed=False,
            ).exists()
        )

    def test_put_add_document_by_paper_id(self):
        """Test PUT adds a document to a list using paper_id"""
        self.client.force_authenticate(user=self.user1)
        response = self.client.put(
            "/user_saved/",
            {
                "list_name": "list2",
                "delete_flag": False,
                "paper_id": self.paper2.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            {
                "success": True,
                "list_name": "list2",
                "document_id": self.doc2.id,
                "delete_flag": False,
            },
        )
        self.assertTrue(
            UserSavedEntry.objects.filter(
                created_by=self.user1,
                parent_list=self.list2,
                unified_document=self.doc2,
                is_removed=False,
            ).exists()
        )

    def test_put_delete_document_by_u_doc_id(self):
        """Test PUT can delete a document from a list using u_doc_id"""
        # Add document first
        self.client.force_authenticate(user=self.user1)
        response = self.client.put(
            "/user_saved/",
            {
                "list_name": "list2",
                "delete_flag": False,
                "u_doc_id": self.doc2.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Then delete it
        response = self.client.put(
            "/user_saved/",
            {
                "list_name": "list2",
                "delete_flag": True,
                "u_doc_id": self.doc2.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            {
                "success": True,
                "list_name": "list2",
                "document_id": self.doc2.id,
                "delete_flag": True,
            },
        )
        self.assertFalse(
            UserSavedEntry.objects.filter(
                created_by=self.user1,
                parent_list=self.list2,
                unified_document=self.doc2,
                is_removed=False,
            ).exists()
        )

    def test_put_delete_document_by_paper_id(self):
        """Test PUT can delete a document from a list using paper_id"""
        # Add document first
        self.client.force_authenticate(user=self.user1)
        response = self.client.put(
            "/user_saved/",
            {
                "list_name": "list2",
                "delete_flag": False,
                "paper_id": self.paper2.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Then delete it
        response = self.client.put(
            "/user_saved/",
            {
                "list_name": "list2",
                "delete_flag": True,
                "paper_id": self.paper2.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            {
                "success": True,
                "list_name": "list2",
                "document_id": self.doc2.id,
                "delete_flag": True,
            },
        )
        self.assertFalse(
            UserSavedEntry.objects.filter(
                created_by=self.user1,
                parent_list=self.list2,
                unified_document=self.doc2,
                is_removed=False,
            ).exists()
        )

    def test_put_no_lookup_key(self):
        """Test PUT fails when no lookup key (u_doc_id or paper_id) is provided"""
        self.client.force_authenticate(user=self.user1)
        response = self.client.put(
            "/user_saved/",
            {
                "list_name": "list2",
                "delete_flag": False,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "No lookup key given")

    def test_put_duplicate_document_in_list(self):
        """Test PUT fails for duplicate document in list"""
        self.client.force_authenticate(user=self.user1)
        response = self.client.put(
            "/user_saved/",
            {
                "list_name": "list1",
                "delete_flag": False,
                "u_doc_id": self.doc1.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Document already in list")

    def test_put_nonexistent_list(self):
        """Test PUT fails for nonexistent list"""
        self.client.force_authenticate(user=self.user1)
        response = self.client.put(
            "/user_saved/",
            {
                "list_name": "nonexistent",
                "delete_flag": False,
                "u_doc_id": self.doc1.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "List not found")

    def test_put_nonexistent_document(self):
        """Test PUT fails for nonexistent document"""
        self.client.force_authenticate(user=self.user1)
        response = self.client.put(
            "/user_saved/",
            {"list_name": "list1", "delete_flag": False, "u_doc_id": "99999"},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "Document not found")

    def test_put_invalid_data(self):
        """Test PUT fails for invalid request body"""
        self.client.force_authenticate(user=self.user1)
        response = self.client.put(
            "/user_saved/", {"list_name": "", "delete_flag": False, "u_doc_id": ""}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_put_unauthenticated(self):
        """Test PUT fails for unauthenticated user"""
        response = self.client.put(
            "/user_saved/",
            {
                "list_name": "list1",
                "delete_flag": False,
                "u_doc_id": self.doc1.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_delete_list(self):
        """Test DELETE soft deletes a list and its entries"""
        self.client.force_authenticate(user=self.user1)

        response = self.client.get("/user_saved/", {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, ["list1", "list2"])

        response = self.client.delete("/user_saved/", {"list_name": "list1"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"success": True, "list_name": "list1"})

        response = self.client.get("/user_saved/", {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, ["list2"])

        self.assertFalse(
            UserSavedEntry.objects.filter(
                parent_list=self.list1, is_removed=False
            ).exists()
        )

    def test_delete_nonexistent_list(self):
        """Test DELETE fails for nonexistent list"""
        self.client.force_authenticate(user=self.user1)
        response = self.client.delete("/user_saved/", {"list_name": "nonexistent"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "List not found")

    def test_delete_invalid_data(self):
        """Test DELETE fails for invalid request body"""
        self.client.force_authenticate(user=self.user1)
        response = self.client.delete("/user_saved/", {"list_name": ""})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_unauthenticated(self):
        """Test DELETE fails for unauthenticated user"""
        response = self.client.delete("/user_saved/", {"list_name": "list1"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_user_scoping(self):
        """Test users cannot access or modify another user's lists"""
        self.client.force_authenticate(user=self.user1)
        # Try to access user2's list
        response = self.client.get("/user_saved/", {"list_name": "list3"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "List not found")

        # Try to add document to user2's list
        response = self.client.put(
            "/user_saved/",
            {
                "list_name": "list3",
                "delete_flag": False,
                "u_doc_id": self.doc1.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "List not found")

        # Try to delete user2's list
        response = self.client.delete("/user_saved/", {"list_name": "list3"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "List not found")

    def test_soft_deleted_lists_excluded(self):
        """Test GET excludes soft-deleted lists and entries"""
        self.client.force_authenticate(user=self.user1)
        # Soft delete list1
        self.list1.is_removed = True
        self.list1.save()
        UserSavedEntry.objects.filter(parent_list=self.list1).update(is_removed=True)

        # Check list1 is not in all lists
        response = self.client.get("/user_saved/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, ["list2"])

        # Check list1 items are not returned
        response = self.client.get("/user_saved/", {"list_name": "list1"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "List not found")

    def test_no_cross_user_entry_deletion(self):
        """Test users deleting their lists will not delete entries in others lists"""
        self.client.force_authenticate(user=self.user1)
        response = self.client.delete("/user_saved/", {"list_name": "list1"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(  # other user list still exists
            UserSavedList.objects.filter(
                created_by=self.user2, list_name="list3", is_removed=False
            ).exists()
        )

    def test_post_restore_soft_deleted_list(self):
        """Test POST restores a soft-deleted list"""
        self.client.force_authenticate(user=self.user1)
        # Soft delete list1
        response = self.client.delete("/user_saved/", {"list_name": "list1"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Re-add list1
        response = self.client.post("/user_saved/", {"list_name": "list1"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"success": True, "list_name": "list1"})
        self.assertTrue(
            UserSavedList.objects.filter(
                created_by=self.user1, list_name="list1", is_removed=False
            ).exists()
        )

    def test_get_lists_containing_document_by_u_doc_id(self):
        """Test getting a list of lists containing a document by u_doc_id"""
        self.client.force_authenticate(user=self.user1)
        # Add list1
        response = self.client.get(f"/user_saved/?u_doc_id={self.doc1.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, ["list1"])

    def test_get_lists_containing_document_by_paper_id(self):
        """Test getting a list of lists containing a document by paper_id"""
        self.client.force_authenticate(user=self.user1)
        # Add list1
        response = self.client.get(f"/user_saved/?paper_id={self.paper1.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, ["list1"])
