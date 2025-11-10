from django.db import IntegrityError
from django.test import TestCase

from researchhub_document.related_models.constants.document_type import PAPER
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_authenticated_user

from user_lists.models import List, ListItem


class ListModelTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("user1")

    def test_list_string_representation_shows_user_and_name(self):
        list_obj = List.objects.create(name="My List", created_by=self.user)
        self.assertEqual(str(list_obj), f"{self.user}:My List")

    def test_list_soft_delete_sets_is_removed(self):
        """Test that deleting a list sets is_removed flag."""
        list_obj = List.objects.create(name="My List", created_by=self.user)
        self.assertFalse(list_obj.is_removed)
        self.assertIsNone(list_obj.is_removed_date)
        
        list_obj.delete()
        list_obj.refresh_from_db()
        
        self.assertTrue(list_obj.is_removed)
        self.assertIsNotNone(list_obj.is_removed_date)

    def test_list_queryset_excludes_removed_lists(self):
        """Test that default queryset excludes removed lists."""
        active_list = List.objects.create(name="Active List", created_by=self.user)
        removed_list = List.objects.create(name="Removed List", created_by=self.user)
        removed_list.delete()
        
        all_lists = List.all_objects.filter(created_by=self.user)
        active_lists = List.objects.filter(created_by=self.user)
        
        self.assertEqual(all_lists.count(), 2)
        self.assertEqual(active_lists.count(), 1)
        self.assertIn(active_list, active_lists)
        self.assertNotIn(removed_list, active_lists)


class ListItemModelTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("user1")
        self.list_obj = List.objects.create(name="My List", created_by=self.user)
        self.doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)

    def test_list_item_string_representation_shows_item_id(self):
        item = ListItem.objects.create(
            parent_list=self.list_obj, unified_document=self.doc, created_by=self.user
        )
        self.assertEqual(str(item), str(item.id))

    def test_list_item_unique_constraint_prevents_duplicates(self):
        """Test that unique constraint prevents duplicate items in the same list."""
        ListItem.objects.create(
            parent_list=self.list_obj, unified_document=self.doc, created_by=self.user
        )
        
        # Attempting to create a duplicate should raise IntegrityError
        with self.assertRaises(IntegrityError):
            ListItem.objects.create(
                parent_list=self.list_obj, unified_document=self.doc, created_by=self.user
            )

    def test_list_item_unique_constraint_allows_duplicates_after_removal(self):
        """Test that unique constraint allows re-adding items after they've been removed."""
        item = ListItem.objects.create(
            parent_list=self.list_obj, unified_document=self.doc, created_by=self.user
        )
        item.delete()
        
        # Should be able to create a new item with the same document after removal
        new_item = ListItem.objects.create(
            parent_list=self.list_obj, unified_document=self.doc, created_by=self.user
        )
        self.assertIsNotNone(new_item)
        self.assertNotEqual(item.id, new_item.id)

    def test_list_item_unique_constraint_allows_same_document_in_different_lists(self):
        """Test that the same document can exist in different lists."""
        other_list = List.objects.create(name="Other List", created_by=self.user)
        
        item1 = ListItem.objects.create(
            parent_list=self.list_obj, unified_document=self.doc, created_by=self.user
        )
        item2 = ListItem.objects.create(
            parent_list=other_list, unified_document=self.doc, created_by=self.user
        )
        
        self.assertIsNotNone(item1)
        self.assertIsNotNone(item2)
        self.assertNotEqual(item1.id, item2.id)

    def test_list_item_soft_delete_sets_is_removed(self):
        """Test that deleting a list item sets is_removed flag."""
        item = ListItem.objects.create(
            parent_list=self.list_obj, unified_document=self.doc, created_by=self.user
        )
        self.assertFalse(item.is_removed)
        self.assertIsNone(item.is_removed_date)
        
        item.delete()
        item.refresh_from_db()
        
        self.assertTrue(item.is_removed)
        self.assertIsNotNone(item.is_removed_date)

    def test_list_item_queryset_excludes_removed_items(self):
        """Test that default queryset excludes removed items."""
        active_item = ListItem.objects.create(
            parent_list=self.list_obj, unified_document=self.doc, created_by=self.user
        )
        other_doc = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)
        removed_item = ListItem.objects.create(
            parent_list=self.list_obj, unified_document=other_doc, created_by=self.user
        )
        removed_item.delete()
        
        all_items = ListItem.all_objects.filter(parent_list=self.list_obj)
        active_items = ListItem.objects.filter(parent_list=self.list_obj)
        
        self.assertEqual(all_items.count(), 2)
        self.assertEqual(active_items.count(), 1)
        self.assertIn(active_item, active_items)
        self.assertNotIn(removed_item, active_items)

    def test_list_item_cascade_delete_when_list_deleted(self):
        """Test that list items are soft-deleted when parent list is deleted."""
        item = ListItem.objects.create(
            parent_list=self.list_obj, unified_document=self.doc, created_by=self.user
        )
        
        self.list_obj.delete()
        item.refresh_from_db()
        
        self.assertTrue(item.is_removed)
        self.assertTrue(self.list_obj.is_removed)
