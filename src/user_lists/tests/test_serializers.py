from django.test import TestCase

from paper.models import Paper
from researchhub_document.related_models.constants.document_type import PAPER
from researchhub_document.related_models.researchhub_unified_document_model import ResearchhubUnifiedDocument
from user.related_models.user_model import User
from user_lists.models import List, ListItem
from user_lists.serializers import (
    ListDetailSerializer,
    ListItemSerializer,
    ListSerializer,
    UserListOverviewSerializer,
)


class ListItemSerializerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user1")
        self.list_obj = List.objects.create(name="My List", created_by=self.user)

    def test_list_item_detail_serializer_with_paper_creates_feed_entry_format(self):
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        Paper.objects.create(
            title="Test Paper",
            uploaded_by=self.user,
            unified_document=unified_doc,
        )
        item = ListItem.objects.create(
            parent_list=self.list_obj, unified_document=unified_doc, created_by=self.user
        )
        serializer = ListItemSerializer(item)
        data = serializer.data

        self.assertIn("unified_document", data)
        unified_doc_data = data["unified_document"]
        self.assertIsInstance(unified_doc_data, dict)
        self.assertIn("id", unified_doc_data)
        self.assertIn("content_type", unified_doc_data)
        self.assertIn("content_object", unified_doc_data)
        self.assertIn("author", unified_doc_data)
        self.assertIn("metrics", unified_doc_data)
        self.assertEqual(unified_doc_data["content_type"], "PAPER")

    def test_list_item_serializer_returns_none_when_no_item_exists(self):
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        item = ListItem.objects.create(
            parent_list=self.list_obj, unified_document=unified_doc, created_by=self.user
        )
        serializer = ListItemSerializer(item)
        data = serializer.data

        self.assertIsNone(data.get("unified_document"))


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

        serializer = ListDetailSerializer(self.list_obj)
        items = serializer.get_items(self.list_obj)
        self.assertIsInstance(items, list)
        self.assertGreater(len(items), 0)


class UserListOverviewSerializerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user1")
        self.list_obj = List.objects.create(name="My List", created_by=self.user)

    def test_lists_returns_empty_list_when_queryset_is_none(self):
        serializer = UserListOverviewSerializer(queryset=None)
        lists = serializer.get_lists(None)
        self.assertEqual(lists, [])

    def test_lists_uses_fallback_path_when_items_are_not_prefetched(self):
        doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        ListItem.objects.create(parent_list=self.list_obj, unified_document=doc, created_by=self.user)
        list_obj_not_prefetched = List.objects.get(id=self.list_obj.id)
        serializer = UserListOverviewSerializer(queryset=[list_obj_not_prefetched])
        lists = serializer.get_lists(None)
        self.assertEqual(len(lists), 1)
        self.assertEqual(len(lists[0]["items"]), 1)
