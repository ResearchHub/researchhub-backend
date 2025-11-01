"""
Tests for export_items_to_personalize management command.
"""

from django.test import TestCase

from analytics.management.commands.export_items_to_personalize import Command
from analytics.tests.helpers import create_prefetched_paper


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
