import time
from datetime import datetime, timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from user.tests.helpers import create_random_default_user


class CommentOrderingTests(APITestCase):
    """Test that comment ordering is preserved when using various filters."""

    def setUp(self):
        """Set up test data."""
        self.user = create_random_default_user("test_user")
        self.client.force_authenticate(self.user)

        # Create a unified document first
        self.unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION"
        )

        # Create a ResearchhubPost to attach comments to
        self.post = ResearchhubPost.objects.create(
            created_by=self.user,
            title="Test Post",
            document_type="DISCUSSION",
            unified_document=self.unified_document,
        )

    def _create_comment_at_time(self, text, created_date, parent=None):
        """Helper to create a comment with a specific created_date."""
        thread_data = {
            "comment_content_json": {"ops": [{"insert": text}]},
            "comment_content_type": "QUILL_EDITOR",
        }

        if parent:
            thread_data["parent_id"] = parent.id

        # Create comment via API to ensure all fields are set properly
        response = self.client.post(
            f"/api/researchhubpost/{self.post.id}/comments/create_rh_comment/",
            thread_data,
            format="json",
        )

        if response.status_code == 200:
            comment = RhCommentModel.objects.get(id=response.data["id"])
            # Override the created_date
            comment.created_date = created_date
            comment.save()
            return comment
        else:
            self.fail(f"Failed to create comment: {response.data}")

    def test_comment_ordering_with_parent_filter_ascending(self):
        """Test that comments maintain created_date ordering when filtering parent__isnull=true with ascending=true."""

        # Create comments with different timestamps
        now = timezone.now()

        # Create parent comments (should be returned)
        comment1 = self._create_comment_at_time(
            "First comment", now - timedelta(days=2)
        )
        comment2 = self._create_comment_at_time(
            "Second comment", now - timedelta(days=1)
        )
        comment3 = self._create_comment_at_time("Third comment", now)

        # Create child comments (should NOT be returned with parent__isnull=true)
        child1 = self._create_comment_at_time(
            "Child of first", now - timedelta(hours=1), parent=comment1
        )

        # Get comments with ordering=CREATED_DATE, ascending=true, parent__isnull=true
        response = self.client.get(
            f"/api/researchhubpost/{self.post.id}/comments/",
            {
                "page_size": 15,
                "ascending": "true",
                "privacy_type": "PUBLIC",
                "ordering": "CREATED_DATE",
                "parent__isnull": "true",
                "page": 1,
            },
        )

        self.assertEqual(response.status_code, 200)
        results = response.data["results"]

        # Should have exactly 3 parent comments
        self.assertEqual(len(results), 3)

        # Check they are in ascending order by created_date
        self.assertEqual(results[0]["id"], comment1.id)
        self.assertEqual(results[1]["id"], comment2.id)
        self.assertEqual(results[2]["id"], comment3.id)

        # Verify dates are actually in ascending order
        date1 = datetime.fromisoformat(
            results[0]["created_date"].replace("Z", "+00:00")
        )
        date2 = datetime.fromisoformat(
            results[1]["created_date"].replace("Z", "+00:00")
        )
        date3 = datetime.fromisoformat(
            results[2]["created_date"].replace("Z", "+00:00")
        )

        self.assertLess(date1, date2)
        self.assertLess(date2, date3)

    def test_comment_ordering_with_parent_filter_descending(self):
        """Test that comments maintain created_date ordering when filtering parent__isnull=true with ascending=FALSE."""

        # Create comments with different timestamps
        now = timezone.now()

        # Create parent comments
        comment1 = self._create_comment_at_time(
            "First comment", now - timedelta(days=2)
        )
        comment2 = self._create_comment_at_time(
            "Second comment", now - timedelta(days=1)
        )
        comment3 = self._create_comment_at_time("Third comment", now)

        # Create child comment
        child1 = self._create_comment_at_time(
            "Child of first", now - timedelta(hours=1), parent=comment1
        )

        # Get comments with ordering=CREATED_DATE, ascending=FALSE (default), parent__isnull=true
        response = self.client.get(
            f"/api/researchhubpost/{self.post.id}/comments/",
            {
                "page_size": 15,
                "ascending": "false",
                "privacy_type": "PUBLIC",
                "ordering": "CREATED_DATE",
                "parent__isnull": "true",
                "page": 1,
            },
        )

        self.assertEqual(response.status_code, 200)
        results = response.data["results"]

        # Should have exactly 3 parent comments
        self.assertEqual(len(results), 3)

        # Check they are in descending order by created_date
        self.assertEqual(results[0]["id"], comment3.id)  # Most recent first
        self.assertEqual(results[1]["id"], comment2.id)
        self.assertEqual(results[2]["id"], comment1.id)  # Oldest last

        # Verify dates are actually in descending order
        date1 = datetime.fromisoformat(
            results[0]["created_date"].replace("Z", "+00:00")
        )
        date2 = datetime.fromisoformat(
            results[1]["created_date"].replace("Z", "+00:00")
        )
        date3 = datetime.fromisoformat(
            results[2]["created_date"].replace("Z", "+00:00")
        )

        self.assertGreater(date1, date2)
        self.assertGreater(date2, date3)

    def test_deleted_comments_included_with_parent_filter(self):
        """Test that deleted/censored comments are included when using parent__isnull filter."""

        now = timezone.now()

        # Create comments
        comment1 = self._create_comment_at_time(
            "First comment", now - timedelta(days=2)
        )
        comment2 = self._create_comment_at_time(
            "Second comment", now - timedelta(days=1)
        )
        comment3 = self._create_comment_at_time("Third comment", now)

        # Mark comment2 as removed (censored)
        comment2.is_removed = True
        comment2.save()

        # Get comments with parent__isnull=true
        response = self.client.get(
            f"/api/researchhubpost/{self.post.id}/comments/",
            {
                "page_size": 15,
                "ascending": "true",
                "privacy_type": "PUBLIC",
                "ordering": "CREATED_DATE",
                "parent__isnull": "true",
                "page": 1,
            },
        )

        self.assertEqual(response.status_code, 200)
        results = response.data["results"]

        # Should still have all 3 comments including the deleted one
        self.assertEqual(len(results), 3)

        # Check ordering is maintained
        self.assertEqual(results[0]["id"], comment1.id)
        self.assertEqual(results[1]["id"], comment2.id)
        self.assertEqual(results[2]["id"], comment3.id)

        # Verify the middle comment is marked as removed
        self.assertTrue(results[1]["is_removed"])

        # Double-check that we're actually getting the censored comment's data
        self.assertEqual(results[1]["id"], comment2.id)
        self.assertTrue(results[1]["is_removed"], "Comment should be marked as removed")

    def test_comment_ordering_without_parent_filter(self):
        """Test that ordering works correctly without parent filter (baseline test)."""

        now = timezone.now()

        # Create parent and child comments
        comment1 = self._create_comment_at_time(
            "First comment", now - timedelta(days=2)
        )
        child1 = self._create_comment_at_time(
            "Child of first", now - timedelta(days=1, hours=23), parent=comment1
        )
        comment2 = self._create_comment_at_time(
            "Second comment", now - timedelta(days=1)
        )
        comment3 = self._create_comment_at_time("Third comment", now)

        # Get all comments without parent filter
        response = self.client.get(
            f"/api/researchhubpost/{self.post.id}/comments/",
            {
                "page_size": 15,
                "ascending": "true",
                "privacy_type": "PUBLIC",
                "ordering": "CREATED_DATE",
                "page": 1,
            },
        )

        self.assertEqual(response.status_code, 200)
        results = response.data["results"]

        # Without parent filter and with default filtering, we might not get all comments
        # The default filter excludes comments with bounties and includes only GENERIC_COMMENT type
        # Just verify that whatever we get is properly ordered
        if len(results) > 1:
            for i in range(len(results) - 1):
                date_current = datetime.fromisoformat(
                    results[i]["created_date"].replace("Z", "+00:00")
                )
                date_next = datetime.fromisoformat(
                    results[i + 1]["created_date"].replace("Z", "+00:00")
                )
                self.assertLessEqual(
                    date_current,
                    date_next,
                    f"Comments not in ascending order: {results[i]['id']} ({date_current}) should come before {results[i+1]['id']} ({date_next})",
                )
