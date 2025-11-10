from django.test import TestCase

from researchhub_document.related_models.constants.document_type import PAPER
from researchhub_document.related_models.researchhub_unified_document_model import ResearchhubUnifiedDocument
from user.related_models.user_model import User
from user_lists.models import List, ListItem
from user_lists.serializers import (
    ListDetailSerializer,
    ListItemDetailSerializer,
    ListSerializer,
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
        self.assertIn("unified_document_data", data)
        self.assertIsInstance(data["unified_document_data"], dict)
        self.assertIn("id", data["unified_document_data"])

    def test_list_item_detail_serializer_returns_minimal_data_when_serialization_fails(self):
        item = ListItem.objects.create(
            parent_list=self.list_obj, unified_document=self.doc, created_by=self.user
        )
        
        original_document_filter = getattr(ResearchhubUnifiedDocument, 'document_filter', None)
        
        class ExceptionProperty:
            def __get__(self, obj, objtype=None):
                raise AttributeError("Test exception to trigger fallback")
        
        setattr(ResearchhubUnifiedDocument, 'document_filter', ExceptionProperty())
        
        try:
            serializer = ListItemDetailSerializer(item, context={"request": None})
            data = serializer.data
            unified_doc_data = data.get("unified_document_data", {})
            
            self.assertIsInstance(unified_doc_data, dict)
            self.assertEqual(len(unified_doc_data), 3)
            self.assertIn("id", unified_doc_data)
            self.assertEqual(unified_doc_data["id"], self.doc.id)
            self.assertIn("document_type", unified_doc_data)
            self.assertEqual(unified_doc_data["document_type"], self.doc.document_type)
            self.assertIn("is_removed", unified_doc_data)
            self.assertEqual(unified_doc_data["is_removed"], self.doc.is_removed)
        finally:
            if original_document_filter is not None:
                setattr(ResearchhubUnifiedDocument, 'document_filter', original_document_filter)
            elif hasattr(ResearchhubUnifiedDocument, 'document_filter'):
                delattr(ResearchhubUnifiedDocument, 'document_filter')


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


