import csv
import os
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from analytics.constants.event_types import FEED_ITEM_CLICK, PAGE_VIEW
from analytics.models import UserInteractions
from researchhub_document.helpers import create_post

User = get_user_model()


class SyncUserInteractionsExportTests(TestCase):
    """Tests for the sync_user_interactions management command export functionality."""

    def setUp(self):
        """Set up test data with both registered and anonymous interactions."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@researchhub.com",
            first_name="Test",
            last_name="User",
        )

        self.post = create_post(created_by=self.user)
        self.unified_document = self.post.unified_document
        self.content_type = ContentType.objects.get_for_model(self.post)

        # Create a registered user interaction
        self.registered_interaction = UserInteractions.objects.create(
            user=self.user,
            event=FEED_ITEM_CLICK,
            unified_document=self.unified_document,
            content_type=self.content_type,
            object_id=self.post.id,
            event_timestamp=timezone.now(),
            external_user_id="ext_registered_123",
        )

        # Create an anonymous interaction (no user, only external_user_id)
        self.anonymous_interaction = UserInteractions.objects.create(
            user=None,
            event=PAGE_VIEW,
            unified_document=self.unified_document,
            content_type=self.content_type,
            object_id=self.post.id,
            event_timestamp=timezone.now(),
            external_user_id="ext_anonymous_456",
        )

    def tearDown(self):
        """Clean up any generated CSV files."""
        for f in os.listdir("."):
            if f.startswith("user_interactions_") and f.endswith(".csv"):
                os.remove(f)

    def test_export_users_only_excludes_anonymous_interactions(self):
        """Test that --users-only flag excludes anonymous interactions."""
        out = StringIO()

        call_command(
            "sync_user_interactions",
            mode="export",
            users_only=True,
            mark_synced=False,
            stdout=out,
        )

        # Find the generated CSV file
        csv_files = [f for f in os.listdir(".") if f.startswith("user_interactions_")]
        self.assertEqual(len(csv_files), 1)

        with open(csv_files[0], "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # Should only have the registered user interaction
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["USER_ID"], str(self.user.id))
        self.assertEqual(rows[0]["EVENT_TYPE"], FEED_ITEM_CLICK)

    def test_export_without_users_only_includes_all_interactions(self):
        """Test that export without --users-only includes both registered and anonymous."""
        out = StringIO()

        call_command(
            "sync_user_interactions",
            mode="export",
            users_only=False,
            mark_synced=False,
            stdout=out,
        )

        # Find the generated CSV file
        csv_files = [f for f in os.listdir(".") if f.startswith("user_interactions_")]
        self.assertEqual(len(csv_files), 1)

        with open(csv_files[0], "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # Should have both interactions
        self.assertEqual(len(rows), 2)

        # Verify we have both registered and anonymous
        user_ids = [row["USER_ID"] for row in rows]
        external_ids = [row["EXTERNAL_USER_ID"] for row in rows]

        self.assertIn(str(self.user.id), user_ids)
        self.assertIn("", user_ids)  # Anonymous has empty USER_ID
        self.assertIn("ext_anonymous_456", external_ids)

    def test_export_users_only_with_multiple_registered_users(self):
        """Test --users-only with multiple registered user interactions."""
        # Create another user and interaction
        user2 = User.objects.create_user(
            username="testuser2",
            email="test2@researchhub.com",
        )
        UserInteractions.objects.create(
            user=user2,
            event=FEED_ITEM_CLICK,
            unified_document=self.unified_document,
            content_type=self.content_type,
            object_id=self.post.id,
            event_timestamp=timezone.now(),
        )

        # Create another anonymous interaction
        UserInteractions.objects.create(
            user=None,
            event=PAGE_VIEW,
            unified_document=self.unified_document,
            content_type=self.content_type,
            object_id=self.post.id,
            event_timestamp=timezone.now(),
            external_user_id="ext_anonymous_789",
        )

        out = StringIO()

        call_command(
            "sync_user_interactions",
            mode="export",
            users_only=True,
            mark_synced=False,
            stdout=out,
        )

        csv_files = [f for f in os.listdir(".") if f.startswith("user_interactions_")]
        self.assertEqual(len(csv_files), 1)

        with open(csv_files[0], "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # Should have 2 registered user interactions (original + user2)
        self.assertEqual(len(rows), 2)

        # All rows should have a USER_ID
        for row in rows:
            self.assertNotEqual(row["USER_ID"], "")
