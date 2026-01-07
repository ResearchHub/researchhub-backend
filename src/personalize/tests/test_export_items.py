"""
Tests for export_items_to_personalize management command.
"""

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from analytics.models import UserInteractions
from personalize.management.commands.export_items import Command
from personalize.tests.helpers import create_prefetched_paper
from user.tests.helpers import create_random_default_user
from user_lists.models import List, ListItem


class ExportQuerysetFilterTests(TestCase):
    """Tests for queryset filtering in export command."""

    def test_removed_documents_excluded_from_export(self):
        """Documents with is_removed=True should be excluded from export."""
        # Arrange
        # Create a normal (non-removed) document
        normal_doc = create_prefetched_paper(title="Normal Paper")
        normal_doc.is_removed = False
        normal_doc.save()

        # Create a removed document
        removed_doc = create_prefetched_paper(title="Removed Paper")
        removed_doc.is_removed = True
        removed_doc.save()

        # Create command instance
        command = Command()

        # Act
        queryset = command._build_base_queryset()
        result_ids = list(queryset.values_list("id", flat=True))

        # Assert
        self.assertIn(
            normal_doc.id,
            result_ids,
            "Normal document should be included in export",
        )
        self.assertNotIn(
            removed_doc.id,
            result_ids,
            "Removed document should be excluded from export",
        )

    def test_documents_with_saved_to_list_interactions_included_in_export(self):
        """
        Documents with DOCUMENT_SAVED_TO_LIST interactions should be
        included in export.
        """
        # Arrange
        user = create_random_default_user("list_export_test_user")
        doc = create_prefetched_paper(title="Saved Paper")

        # Create a List and ListItem (signal would normally create interaction)
        user_list = List.objects.create(name="My Reading List", created_by=user)
        list_item = ListItem.objects.create(
            parent_list=user_list,
            unified_document=doc,
            created_by=user,
        )

        # Manually create the UserInteraction as if the signal had run
        list_item_content_type = ContentType.objects.get_for_model(ListItem)
        UserInteractions.objects.create(
            user=user,
            event="DOCUMENT_SAVED_TO_LIST",
            unified_document=doc,
            content_type=list_item_content_type,
            object_id=list_item.id,
            event_timestamp=list_item.created_date,
            is_synced_with_personalize=False,
        )

        # Create command instance
        command = Command()

        # Act - Get queryset with interactions filter
        queryset = command._get_queryset(
            since_publish_date=None,
            ids=None,
            with_interactions=True,
            with_posts=False,
            post_types=None,
        )
        result_ids = list(queryset.values_list("id", flat=True))

        # Assert
        self.assertIn(
            doc.id,
            result_ids,
            "Document with DOCUMENT_SAVED_TO_LIST interaction should be "
            "included in export",
        )
