"""
Comprehensive tests for user saved lists functionality
Tests for the enhanced user saved lists feature
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from paper.related_models.paper_model import Paper
from researchhub_document.related_models.constants.document_type import PAPER
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)

from .models import UserSavedEntry, UserSavedList, UserSavedListPermission

User = get_user_model()


# ============================================================================
# MODEL TESTS
# ============================================================================


class UserSavedListModelTests(TestCase):
    """Test UserSavedList model functionality"""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser")

    def test_create_list(self):
        """Test creating a basic list"""
        list_obj = UserSavedList.objects.create(
            created_by=self.user,
            list_name="Test List",
            description="A test list",
            is_public=True,
            tags=["test", "example"],
        )

        self.assertEqual(list_obj.list_name, "Test List")
        self.assertEqual(list_obj.description, "A test list")
        self.assertTrue(list_obj.is_public)
        self.assertEqual(list_obj.tags, ["test", "example"])
        self.assertIsNotNone(list_obj.share_token)

    def test_share_token_generation(self):
        """Test that share token is generated for public lists"""
        list_obj = UserSavedList.objects.create(
            created_by=self.user, list_name="Public List", is_public=True
        )

        self.assertIsNotNone(list_obj.share_token)
        self.assertEqual(len(list_obj.share_token), 32)

    def test_share_url_generation(self):
        """Test share URL generation"""
        list_obj = UserSavedList.objects.create(
            created_by=self.user, list_name="Public List", is_public=True
        )

        share_url = list_obj.get_share_url()
        self.assertIsNotNone(share_url)
        self.assertIn(list_obj.share_token, share_url)

    def test_unique_list_name_per_user(self):
        """Test that list names are unique per user"""
        UserSavedList.objects.create(created_by=self.user, list_name="Test List")

        # Should be able to create another list with same name for different user
        other_user = User.objects.create_user(username="otheruser")
        UserSavedList.objects.create(created_by=other_user, list_name="Test List")

        # Should not be able to create duplicate for same user
        with self.assertRaises(Exception):  # IntegrityError or similar
            UserSavedList.objects.create(created_by=self.user, list_name="Test List")

    def test_soft_delete(self):
        """Test soft deletion of lists"""
        list_obj = UserSavedList.objects.create(
            created_by=self.user, list_name="Test List"
        )

        self.assertFalse(list_obj.is_removed)

        list_obj.is_removed = True
        list_obj.save()

        # Should not appear in normal queries
        self.assertFalse(UserSavedList.objects.filter(list_name="Test List").exists())

        # Should still exist in database by querying directly
        list_obj.refresh_from_db()
        self.assertTrue(list_obj.is_removed)


class UserSavedEntryModelTests(TestCase):
    """Test UserSavedEntry model functionality"""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser")
        self.list_obj = UserSavedList.objects.create(
            created_by=self.user, list_name="Test List"
        )
        self.doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        self.paper = Paper.objects.create(unified_document=self.doc, title="Test Paper")

    def test_create_entry(self):
        """Test creating a basic entry"""
        entry = UserSavedEntry.objects.create(
            created_by=self.user, parent_list=self.list_obj, unified_document=self.doc
        )

        self.assertEqual(entry.parent_list, self.list_obj)
        self.assertEqual(entry.unified_document, self.doc)
        self.assertFalse(entry.document_deleted)

    def test_document_deletion_handling(self):
        """Test handling of deleted documents"""
        entry = UserSavedEntry.objects.create(
            created_by=self.user, parent_list=self.list_obj, unified_document=self.doc
        )

        # Simulate document deletion
        entry.document_deleted = True
        entry.document_deleted_date = timezone.now()
        entry.document_title_snapshot = "Deleted Paper"
        entry.document_type_snapshot = "PAPER"
        entry.unified_document = None
        entry.save()

        self.assertTrue(entry.document_deleted)
        self.assertIsNotNone(entry.document_deleted_date)
        self.assertEqual(entry.document_title_snapshot, "Deleted Paper")
        self.assertIsNone(entry.unified_document)

    def test_soft_delete(self):
        """Test soft deletion of entries"""
        entry = UserSavedEntry.objects.create(
            created_by=self.user, parent_list=self.list_obj, unified_document=self.doc
        )

        self.assertFalse(entry.is_removed)

        entry.is_removed = True
        entry.save()

        # Should not appear in normal queries
        self.assertFalse(UserSavedEntry.objects.filter(id=entry.id).exists())

        # Should still exist in database by refreshing
        entry.refresh_from_db()
        self.assertTrue(entry.is_removed)


class UserSavedListPermissionModelTests(TestCase):
    """Test UserSavedListPermission model functionality"""

    def setUp(self):
        self.user1 = User.objects.create_user(username="user1")
        self.user2 = User.objects.create_user(username="user2")
        self.list_obj = UserSavedList.objects.create(
            created_by=self.user1, list_name="Test List"
        )

    def test_create_permission(self):
        """Test creating a permission"""
        permission = UserSavedListPermission.objects.create(
            list=self.list_obj,
            user=self.user2,
            permission="VIEW",
            created_by=self.user1,
        )

        self.assertEqual(permission.list, self.list_obj)
        self.assertEqual(permission.user, self.user2)
        self.assertEqual(permission.permission, "VIEW")

    def test_unique_user_per_list(self):
        """Test that a user can only have one permission per list"""
        UserSavedListPermission.objects.create(
            list=self.list_obj,
            user=self.user2,
            permission="EDIT",
            created_by=self.user1,
        )

        # Should not be able to create duplicate permission
        with self.assertRaises(Exception):  # IntegrityError or similar
            UserSavedListPermission.objects.create(
                list=self.list_obj,
                user=self.user2,
                permission="EDIT",
                created_by=self.user1,
            )

    def test_permission_choices(self):
        """Test permission choices"""
        permission = UserSavedListPermission.objects.create(
            list=self.list_obj,
            user=self.user2,
            permission="ADMIN",
            created_by=self.user1,
        )

        self.assertIn(permission.permission, ["VIEW", "EDIT", "ADMIN"])


# ============================================================================
# API TESTS
# ============================================================================


class UserSavedListAPITests(APITestCase):
    """Test the enhanced API endpoints"""

    def setUp(self):
        self.user1 = User.objects.create_user(username="user1", email="user1@test.com")
        self.user2 = User.objects.create_user(username="user2", email="user2@test.com")

        # Create test documents
        self.doc1 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        self.doc2 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        self.paper1 = Paper.objects.create(
            unified_document=self.doc1, title="Test Paper 1"
        )
        self.paper2 = Paper.objects.create(
            unified_document=self.doc2, title="Test Paper 2"
        )

    def test_create_list(self):
        """Test creating a new list via API"""
        self.client.force_authenticate(user=self.user1)

        data = {
            "list_name": "My Research List",
            "description": "A collection of important papers",
            "tags": ["machine-learning", "neuroscience"],
            "is_public": True,
        }

        response = self.client.post("/api/lists/", data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["list_name"], "My Research List")
        self.assertEqual(
            response.data["description"], "A collection of important papers"
        )
        self.assertEqual(response.data["tags"], ["machine-learning", "neuroscience"])
        self.assertTrue(response.data["is_public"])
        self.assertIsNotNone(response.data["share_url"])

    def test_list_lists(self):
        """Test listing user's lists"""
        # Create lists for user1
        list1 = UserSavedList.objects.create(  # noqa: F841
            created_by=self.user1, list_name="List 1", is_public=True
        )
        list2 = UserSavedList.objects.create(  # noqa: F841
            created_by=self.user1, list_name="List 2", is_public=False
        )

        # Create a list for user2
        list3 = UserSavedList.objects.create(  # noqa: F841
            created_by=self.user2, list_name="List 3", is_public=True
        )

        self.client.force_authenticate(user=self.user1)
        response = self.client.get("/api/lists/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Handle paginated response
        if isinstance(response.data, dict) and "results" in response.data:
            # Paginated response - use the results
            data_list = response.data["results"]
        else:
            # Direct list response
            data_list = response.data

        # Should see own lists + public list from user2
        list_names = [item["list_name"] for item in data_list]
        self.assertIn("List 1", list_names)
        self.assertIn("List 2", list_names)
        self.assertIn("List 3", list_names)

        # Verify we have at least these 3 lists
        self.assertGreaterEqual(len(data_list), 3)

    def test_get_list_detail(self):
        """Test getting detailed list information"""
        list_obj = UserSavedList.objects.create(
            created_by=self.user1, list_name="Test List"
        )

        # Add a document to the list
        entry = UserSavedEntry.objects.create(  # noqa: F841
            created_by=self.user1, parent_list=list_obj, unified_document=self.doc1
        )

        self.client.force_authenticate(user=self.user1)
        response = self.client.get(f"/api/lists/{list_obj.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["list_name"], "Test List")
        self.assertEqual(len(response.data["documents"]), 1)

        # Check that document info exists, but be flexible about title
        doc_info = response.data["documents"][0]["document_info"]
        self.assertIsNotNone(doc_info)
        self.assertEqual(doc_info["id"], self.doc1.id)
        self.assertEqual(doc_info["document_type"], "PAPER")

    def test_add_document_to_list(self):
        """Test adding a document to a list"""
        list_obj = UserSavedList.objects.create(
            created_by=self.user1, list_name="Test List"
        )

        self.client.force_authenticate(user=self.user1)
        data = {"u_doc_id": self.doc1.id}

        response = self.client.post(f"/api/lists/{list_obj.id}/add_document/", data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["success"], True)
        self.assertEqual(response.data["list_name"], "Test List")
        self.assertEqual(response.data["document_id"], self.doc1.id)

        # Verify the entry was created
        entry = UserSavedEntry.objects.get(
            parent_list=list_obj, unified_document=self.doc1
        )
        self.assertFalse(entry.is_removed)

    def test_remove_document_from_list(self):
        """Test removing a document from a list"""
        list_obj = UserSavedList.objects.create(
            created_by=self.user1, list_name="Test List"
        )

        # Add a document first
        entry = UserSavedEntry.objects.create(
            created_by=self.user1, parent_list=list_obj, unified_document=self.doc1
        )

        self.client.force_authenticate(user=self.user1)
        data = {"u_doc_id": self.doc1.id}

        response = self.client.post(f"/api/lists/{list_obj.id}/remove_document/", data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["success"], True)

        # Verify the entry was soft deleted
        entry.refresh_from_db()
        self.assertTrue(entry.is_removed)

    def test_add_permission(self):
        """Test adding permission for a user"""
        list_obj = UserSavedList.objects.create(
            created_by=self.user1, list_name="Test List"
        )

        self.client.force_authenticate(user=self.user1)
        data = {"username": "user2@test.com", "permission": "EDIT"}

        response = self.client.post(f"/api/lists/{list_obj.id}/add_permission/", data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["permission"], "EDIT")
        self.assertEqual(response.data["username"], "user2@test.com")

        # Verify the permission was created
        permission = UserSavedListPermission.objects.get(list=list_obj, user=self.user2)
        self.assertEqual(permission.permission, "EDIT")

    def test_remove_permission(self):
        """Test removing permission for a user"""
        list_obj = UserSavedList.objects.create(
            created_by=self.user1, list_name="Test List"
        )

        # Add permission first
        permission = UserSavedListPermission.objects.create(  # noqa: F841
            list=list_obj,
            user=self.user2,
            permission="EDIT",
            created_by=self.user1,
        )

        self.client.force_authenticate(user=self.user1)
        data = {"username": "user2@test.com"}

        response = self.client.post(
            f"/api/lists/{list_obj.id}/remove_permission/", data
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["success"], True)
        self.assertEqual(response.data["username"], "user2@test.com")

        # Verify the permission was removed
        self.assertFalse(
            UserSavedListPermission.objects.filter(
                list=list_obj, user=self.user2
            ).exists()
        )

    def test_list_permissions(self):
        """Test listing permissions for a list"""
        list_obj = UserSavedList.objects.create(
            created_by=self.user1, list_name="Test List"
        )

        # Add permissions
        UserSavedListPermission.objects.create(
            list=list_obj,
            user=self.user2,
            permission="EDIT",
            created_by=self.user1,
        )

        self.client.force_authenticate(user=self.user1)
        response = self.client.get(f"/api/lists/{list_obj.id}/permissions/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["username"], "user2@test.com")
        self.assertEqual(response.data[0]["permission"], "EDIT")

    def test_update_list(self):
        """Test updating a list"""
        list_obj = UserSavedList.objects.create(
            created_by=self.user1,
            list_name="Original Name",
            description="Original description",
            is_public=False,
        )

        self.client.force_authenticate(user=self.user1)
        data = {
            "list_name": "Updated Name",
            "description": "Updated description",
            "is_public": True,
            "tags": ["updated", "tags"],
        }

        response = self.client.put(f"/api/lists/{list_obj.id}/", data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["list_name"], "Updated Name")
        self.assertEqual(response.data["description"], "Updated description")
        self.assertTrue(response.data["is_public"])
        self.assertEqual(response.data["tags"], ["updated", "tags"])

    def test_delete_list(self):
        """Test deleting a list"""
        list_obj = UserSavedList.objects.create(
            created_by=self.user1, list_name="Test List"
        )

        # Add a document to the list
        entry = UserSavedEntry.objects.create(
            created_by=self.user1, parent_list=list_obj, unified_document=self.doc1
        )

        self.client.force_authenticate(user=self.user1)
        response = self.client.delete(f"/api/lists/{list_obj.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["success"], True)

        # Verify the list and entries were soft deleted
        list_obj.refresh_from_db()
        entry.refresh_from_db()
        self.assertTrue(list_obj.is_removed)
        self.assertTrue(entry.is_removed)

    def test_permission_denied_access(self):
        """Test that users cannot access lists they don't have permission for"""
        list_obj = UserSavedList.objects.create(
            created_by=self.user1, list_name="Private List", is_public=False
        )

        # User2 should not be able to access user1's private list
        self.client.force_authenticate(user=self.user2)
        response = self.client.get(f"/api/lists/{list_obj.id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_shared_list_access(self):
        """Test that users can access lists shared with them"""
        list_obj = UserSavedList.objects.create(
            created_by=self.user1, list_name="Shared List", is_public=False
        )

        # Share the list with user2
        UserSavedListPermission.objects.create(
            list=list_obj, user=self.user2, permission="VIEW", created_by=self.user1
        )

        self.client.force_authenticate(user=self.user2)
        response = self.client.get(f"/api/lists/{list_obj.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["list_name"], "Shared List")

    def test_public_list_access(self):
        """Test that users can access public lists"""
        list_obj = UserSavedList.objects.create(
            created_by=self.user1, list_name="Public List", is_public=True
        )

        self.client.force_authenticate(user=self.user2)
        response = self.client.get(f"/api/lists/{list_obj.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["list_name"], "Public List")


class UserSavedSharedListAPITests(APITestCase):
    """Test shared list access via share token"""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser")
        self.doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        self.paper = Paper.objects.create(unified_document=self.doc, title="Test Paper")

    def test_shared_list_access(self):
        """Test accessing a shared list via share token"""
        list_obj = UserSavedList.objects.create(
            created_by=self.user,
            list_name="Shared List",
            description="A shared list",
            is_public=True,
        )

        # Add a document to the list
        entry = UserSavedEntry.objects.create(
            created_by=self.user, parent_list=list_obj, unified_document=self.doc
        )

        response = self.client.get(f"/shared/list/{list_obj.share_token}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["list_name"], "Shared List")
        self.assertEqual(response.data["description"], "A shared list")
        self.assertEqual(len(response.data["documents"]), 1)

        # Check document info exists but be flexible about title
        doc_data = response.data["documents"][0]
        self.assertIsNotNone(doc_data)
        self.assertEqual(doc_data["entry_id"], entry.id)
        self.assertFalse(doc_data["is_deleted"])

    def test_shared_list_with_deleted_document(self):
        """Test shared list access when a document has been deleted"""
        list_obj = UserSavedList.objects.create(
            created_by=self.user,
            list_name="List with Deleted Doc",
            is_public=True,
        )

        # Create an entry for a deleted document
        entry = UserSavedEntry.objects.create(
            created_by=self.user,
            parent_list=list_obj,
            unified_document=None,  # Document was deleted
            document_deleted=True,
            document_deleted_date=timezone.now(),
            document_title_snapshot="Deleted Paper",
            document_type_snapshot="PAPER",
        )

        response = self.client.get(f"/shared/list/{list_obj.share_token}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["documents"]), 1)

        doc_data = response.data["documents"][0]
        self.assertTrue(doc_data["is_deleted"])
        self.assertEqual(doc_data["entry_id"], entry.id)
        self.assertEqual(doc_data["title"], "Deleted Paper")
        self.assertEqual(doc_data["document_type"], "PAPER")

    def test_invalid_share_token(self):
        """Test accessing with invalid share token"""
        response = self.client.get("/shared/list/invalid-token/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_private_list_share_token(self):
        """Test that private lists cannot be accessed via share token"""
        list_obj = UserSavedList.objects.create(
            created_by=self.user,
            list_name="Private List",
            is_public=False,
        )

        response = self.client.get(f"/shared/list/{list_obj.share_token}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
