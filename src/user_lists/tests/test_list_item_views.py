from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from feed.models import FeedEntry
from paper.models import Paper
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
        self.paper = Paper.objects.create(
            title="Test Paper",
            paper_publish_date="2025-01-01",
            unified_document=self.doc,
            uploaded_by=self.user,
        )
        self.paper_content_type = ContentType.objects.get_for_model(Paper)

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
        item = ListItem.all_objects.get(pk=item.pk)
        self.assertTrue(item.is_removed)

    def test_user_cannot_delete_item_from_another_users_list(self):
        other_list = List.objects.create(name="Other List", created_by=self.other_user)
        item = ListItem.objects.create(parent_list=other_list, unified_document=self.doc, created_by=self.other_user)
        response = self.client.delete(f"/api/user_list_item/{item.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_requires_parent_list_param(self):
        response = self.client.get("/api/user_list_item/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("parent_list is required", response.data["error"])

    def test_list_returns_404_for_nonexistent_list(self):
        response = self.client.get("/api/user_list_item/?parent_list=99999")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_returns_items_with_feed_entries(self):
        item = ListItem.objects.create(parent_list=self.list, unified_document=self.doc, created_by=self.user)
        FeedEntry.objects.create(
            unified_document=self.doc,
            user=self.user,
            content_type=self.paper_content_type,
            object_id=self.paper.id,
            action=FeedEntry.PUBLISH,
            action_date=timezone.now(),
        )
        response = self.client.get(f"/api/user_list_item/?parent_list={self.list.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertIsNotNone(response.data["results"][0]["feed_entry"])

    def test_list_item_without_feed_entry_returns_none(self):
        item = ListItem.objects.create(parent_list=self.list, unified_document=self.doc, created_by=self.user)
        response = self.client.get(f"/api/user_list_item/?parent_list={self.list.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertIsNone(response.data["results"][0]["feed_entry"])

