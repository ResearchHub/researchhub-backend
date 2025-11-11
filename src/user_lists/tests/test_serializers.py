from django.test import TestCase
from unittest.mock import patch

from paper.models import Paper
from researchhub_document.related_models.constants.document_type import PAPER
from researchhub_document.related_models.researchhub_unified_document_model import ResearchhubUnifiedDocument
from user.related_models.user_model import User
from user_lists.models import List, ListItem
from user_lists.serializers import (
    ListDetailSerializer,
    ListItemDetailSerializer,
    ListSerializer,
    ToggleListItemResponseSerializer,
    UnifiedDocumentForListSerializer,
    UserCheckResponseSerializer,
)


class ListItemDetailSerializerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user1")
        self.list_obj = List.objects.create(name="My List", created_by=self.user)
        self.doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)

    def test_list_item_detail_serializer_includes_unified_document_data(self):
        item = ListItem.objects.create(
            parent_list=self.list_obj, unified_document=self.doc, created_by=self.user
        )
        serializer = ListItemDetailSerializer(item, context={"request": None})
        data = serializer.data
        self.assertIn("unified_document", data)
        self.assertIsInstance(data["unified_document"], dict)
        self.assertIn("id", data["unified_document"])

    def test_list_item_detail_serializer_returns_minimal_data_when_serialization_fails(self):
        item = ListItem.objects.create(
            parent_list=self.list_obj, unified_document=self.doc, created_by=self.user
        )
        
        with patch.object(UnifiedDocumentForListSerializer, 'get_hubs', side_effect=Exception("Test exception")):
            serializer = ListItemDetailSerializer(item, context={"request": None})
            data = serializer.data
            unified_doc_data = data.get("unified_document", {})
            
            self.assertIsInstance(unified_doc_data, dict)
            self.assertEqual(len(unified_doc_data), 3)
            self.assertIn("id", unified_doc_data)
            self.assertEqual(unified_doc_data["id"], self.doc.id)
            self.assertIn("document_type", unified_doc_data)
            self.assertEqual(unified_doc_data["document_type"], self.doc.document_type)
            self.assertIn("is_removed", unified_doc_data)
            self.assertEqual(unified_doc_data["is_removed"], self.doc.is_removed)


class ListSerializerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user1")
        self.list_obj = List.objects.create(name="My List", created_by=self.user)

    def test_list_serializer_counts_only_active_items(self):
        doc1 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        doc2 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        item1 = ListItem.objects.create(parent_list=self.list_obj, unified_document=doc1, created_by=self.user)
        ListItem.objects.create(parent_list=self.list_obj, unified_document=doc2, created_by=self.user)
        item1.delete()
        
        serializer = ListSerializer(self.list_obj)
        self.assertEqual(serializer.get_items_count(self.list_obj), 1)

    def test_list_serializer_uses_prefetched_data(self):
        doc1 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        doc2 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        ListItem.objects.create(parent_list=self.list_obj, unified_document=doc1, created_by=self.user)
        ListItem.objects.create(parent_list=self.list_obj, unified_document=doc2, created_by=self.user)
        
        list_obj_prefetched = List.objects.prefetch_related("items").get(id=self.list_obj.id)
        serializer = ListSerializer(list_obj_prefetched)
        
        self.assertTrue(hasattr(list_obj_prefetched, '_prefetched_objects_cache'))
        self.assertIn('items', list_obj_prefetched._prefetched_objects_cache)
        self.assertEqual(serializer.get_items_count(list_obj_prefetched), 2)


class ListDetailSerializerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user1")
        self.list_obj = List.objects.create(name="My List", created_by=self.user)

    def test_list_detail_serializer_returns_paginated_items(self):
        doc1 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        doc2 = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        ListItem.objects.create(parent_list=self.list_obj, unified_document=doc1, created_by=self.user)
        ListItem.objects.create(parent_list=self.list_obj, unified_document=doc2, created_by=self.user)
        
        serializer = ListDetailSerializer(self.list_obj, context={"request": None})
        items = serializer.get_items(self.list_obj)
        self.assertIsInstance(items, list)
        self.assertGreater(len(items), 0)


class UnifiedDocumentForListSerializerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user1")
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        self.doc = Paper.objects.create(
            title="Test Paper",
            uploaded_by=self.user,
            unified_document=unified_doc,
        ).unified_document

    def test_unified_document_serializer_includes_all_fields(self):
        serializer = UnifiedDocumentForListSerializer(self.doc, context={"request": None})
        data = serializer.data
        
        self.assertIn("id", data)
        self.assertIn("created_date", data)
        self.assertIn("title", data)
        self.assertIn("slug", data)
        self.assertIn("is_removed", data)
        self.assertIn("document_type", data)
        self.assertIn("hubs", data)
        self.assertIn("created_by", data)
        self.assertIn("documents", data)
        self.assertIn("score", data)
        self.assertIn("hot_score", data)
        self.assertIn("reviews", data)
        self.assertIn("fundraise", data)
        self.assertIn("grant", data)

    def test_get_hubs_returns_list_with_id_name_slug(self):
        serializer = UnifiedDocumentForListSerializer(self.doc, context={"request": None})
        hubs = serializer.get_hubs(self.doc)
        
        self.assertIsInstance(hubs, list)

    def test_get_created_by_returns_user_data(self):
        serializer = UnifiedDocumentForListSerializer(self.doc, context={"request": None})
        created_by = serializer.get_created_by(self.doc)
        
        self.assertIsNotNone(created_by)
        self.assertIn("id", created_by)
        self.assertIn("first_name", created_by)
        self.assertIn("last_name", created_by)

    def test_get_created_by_returns_none_when_no_creator(self):
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        Paper.objects.create(
            title="Test Paper",
            uploaded_by=None,
            unified_document=unified_doc,
        )
        serializer = UnifiedDocumentForListSerializer(unified_doc, context={"request": None})
        created_by = serializer.get_created_by(unified_doc)
        
        self.assertIsNone(created_by)

    def test_get_reviews_returns_default_when_no_reviews(self):
        serializer = UnifiedDocumentForListSerializer(self.doc, context={"request": None})
        reviews = serializer.get_reviews(self.doc)
        
        self.assertIsInstance(reviews, dict)
        self.assertEqual(reviews["avg"], 0.0)
        self.assertEqual(reviews["count"], 0)

    def test_get_fundraise_returns_none_when_no_fundraise(self):
        serializer = UnifiedDocumentForListSerializer(self.doc, context={"request": None})
        fundraise = serializer.get_fundraise(self.doc)
        
        self.assertIsNone(fundraise)

    def test_get_grant_returns_none_when_no_grant(self):
        serializer = UnifiedDocumentForListSerializer(self.doc, context={"request": None})
        grant = serializer.get_grant(self.doc)
        
        self.assertIsNone(grant)

    def test_get_documents_handles_paper_type(self):
        serializer = UnifiedDocumentForListSerializer(self.doc, context={"request": None})
        documents = serializer.get_documents(self.doc)
        
        self.assertIsNotNone(documents)

    def test_get_title_handles_paper(self):
        serializer = UnifiedDocumentForListSerializer(self.doc, context={"request": None})
        title = serializer.get_title(self.doc)
        
        self.assertIsNotNone(title)

    def test_get_slug_handles_paper(self):
        serializer = UnifiedDocumentForListSerializer(self.doc, context={"request": None})
        slug = serializer.get_slug(self.doc)
        
        self.assertIsNotNone(slug)


class ToggleListItemResponseSerializerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user1")
        self.list_obj = List.objects.create(name="My List", created_by=self.user)
        self.doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)

    def test_toggle_response_serializer_with_added_action(self):
        item = ListItem.objects.create(
            parent_list=self.list_obj, unified_document=self.doc, created_by=self.user
        )
        response_data = {
            "action": "added",
            "item": item,
            "success": True,
        }
        serializer = ToggleListItemResponseSerializer(response_data, context={"request": None})
        data = serializer.data
        
        self.assertEqual(data["action"], "added")
        self.assertEqual(data["success"], True)
        self.assertIsNotNone(data["item"])
        self.assertIn("id", data["item"])

    def test_toggle_response_serializer_with_removed_action(self):
        response_data = {
            "action": "removed",
            "item": None,
            "success": True,
        }
        serializer = ToggleListItemResponseSerializer(response_data, context={"request": None})
        data = serializer.data
        
        self.assertEqual(data["action"], "removed")
        self.assertEqual(data["success"], True)
        self.assertIsNone(data["item"])


class UserCheckResponseSerializerTests(TestCase):
    def test_user_check_response_serializer(self):
        response_data = {
            "lists": [
                {
                    "id": 1,
                    "name": "Test List",
                    "is_public": False,
                    "items": [
                        {"id": 1, "unified_document_id": 10},
                        {"id": 2, "unified_document_id": 11},
                    ],
                }
            ]
        }
        serializer = UserCheckResponseSerializer(response_data)
        data = serializer.data
        
        self.assertIn("lists", data)
        self.assertEqual(len(data["lists"]), 1)
        list_data = data["lists"][0]
        self.assertEqual(list_data["id"], 1)
        self.assertEqual(list_data["name"], "Test List")
        self.assertEqual(list_data["is_public"], False)
        self.assertEqual(len(list_data["items"]), 2)
        self.assertEqual(list_data["items"][0]["id"], 1)
        self.assertEqual(list_data["items"][0]["unified_document_id"], 10)


