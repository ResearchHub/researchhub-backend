from rest_framework import status
from rest_framework.test import APITestCase

from paper.models import Paper
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import RhCommentThreadModel
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    PAPER,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
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
        self.doc.created_by = self.user
        self.doc.save()
        self.paper = Paper.objects.create(
            title="Test Paper",
            paper_publish_date="2025-01-01",
            unified_document=self.doc,
            uploaded_by=self.user,
        )

    def test_user_can_add_item_to_list(self):
        response = self.client.post(f"/api/list/{self.list.id}/item/", {
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
        response = self.client.post(f"/api/list/{self.list.id}/item/", {
            "parent_list": self.list.id,
            "unified_document": self.doc.id,
        })
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_cannot_add_duplicate_item_to_list(self):
        ListItem.objects.create(parent_list=self.list, unified_document=self.doc, created_by=self.user)
        response = self.client.post(f"/api/list/{self.list.id}/item/", {
            "parent_list": self.list.id,
            "unified_document": self.doc.id,
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_add_item_to_another_users_list(self):
        other_list = List.objects.create(name="Other List", created_by=self.other_user)
        response = self.client.post(f"/api/list/{other_list.id}/item/", {
            "parent_list": other_list.id,
            "unified_document": self.doc.id,
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_add_item_to_deleted_list(self):
        self.list.is_removed = True
        self.list.save()
        response = self.client.post(f"/api/list/{self.list.id}/item/", {
            "parent_list": self.list.id,
            "unified_document": self.doc.id,
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_user_can_delete_item_from_their_list(self):
        item = ListItem.objects.create(parent_list=self.list, unified_document=self.doc, created_by=self.user)
        response = self.client.delete(f"/api/list/{self.list.id}/item/{item.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        item = ListItem.all_objects.get(pk=item.pk)
        self.assertTrue(item.is_removed)

    def test_user_cannot_delete_item_from_another_users_list(self):
        other_list = List.objects.create(name="Other List", created_by=self.other_user)
        item = ListItem.objects.create(parent_list=other_list, unified_document=self.doc, created_by=self.other_user)
        response = self.client.delete(f"/api/list/{other_list.id}/item/{item.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_listing_items_requires_valid_list_id(self):
        response = self.client.get("/api/list/99999/item/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("List not found", response.data["error"])

    def test_listing_items_returns_document_data(self):
        ListItem.objects.create(
            parent_list=self.list, unified_document=self.doc, created_by=self.user
        )
        response = self.client.get(f"/api/list/{self.list.id}/item/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertIsNotNone(response.data["results"][0]["document"])
        self.assertEqual(
            response.data["results"][0]["document"]["content_type"], "PAPER"
        )

    def test_list_item_includes_paper_content(self):
        ListItem.objects.create(
            parent_list=self.list, unified_document=self.doc, created_by=self.user
        )
        response = self.client.get(f"/api/list/{self.list.id}/item/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        document_data = response.data["results"][0]["document"]
        self.assertIsNotNone(document_data["content_object"])
        self.assertEqual(document_data["content_object"]["title"], "Test Paper")
        self.assertIn("metrics", document_data)

    def test_list_item_includes_post_content(self):
        post_doc = ResearchhubUnifiedDocument.objects.create(document_type=DISCUSSION)
        post_doc.created_by = self.user
        post_doc.save()
        ResearchhubPost.objects.create(
            title="Test Post",
            renderable_text="Test content",
            unified_document=post_doc,
            created_by=self.user,
            document_type=DISCUSSION,
        )
        ListItem.objects.create(
            parent_list=self.list, unified_document=post_doc, created_by=self.user
        )
        response = self.client.get(f"/api/list/{self.list.id}/item/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        document_data = response.data["results"][0]["document"]
        self.assertEqual(document_data["content_type"], "RESEARCHHUBPOST")
        self.assertEqual(document_data["content_object"]["title"], "Test Post")

    def test_listing_items_returns_empty_when_list_is_empty(self):
        response = self.client.get(f"/api/list/{self.list.id}/item/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

    def test_list_item_metrics_include_votes(self):
        ListItem.objects.create(
            parent_list=self.list, unified_document=self.doc, created_by=self.user
        )
        response = self.client.get(f"/api/list/{self.list.id}/item/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        metrics = response.data["results"][0]["document"]["metrics"]
        self.assertIn("votes", metrics)

    def test_list_item_metrics_include_comments(self):
        ListItem.objects.create(
            parent_list=self.list, unified_document=self.doc, created_by=self.user
        )
        thread = RhCommentThreadModel.objects.create(
            content_object=self.paper, created_by=self.user
        )
        RhCommentModel.objects.create(
            thread=thread, created_by=self.user, comment_content_json={}
        )
        response = self.client.get(f"/api/list/{self.list.id}/item/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        metrics = response.data["results"][0]["document"]["metrics"]
        self.assertIn("comments", metrics)

    def test_listing_items_excludes_removed_documents(self):
        ListItem.objects.create(
            parent_list=self.list, unified_document=self.doc, created_by=self.user
        )
        self.doc.is_removed = True
        self.doc.save()
        response = self.client.get(f"/api/list/{self.list.id}/item/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

    def test_document_field_includes_author_info(self):
        ListItem.objects.create(
            parent_list=self.list, unified_document=self.doc, created_by=self.user
        )
        response = self.client.get(f"/api/list/{self.list.id}/item/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        document_data = response.data["results"][0]["document"]
        self.assertIsNotNone(document_data["author"])
        self.assertEqual(document_data["author"]["id"], self.user.author_profile.id)

