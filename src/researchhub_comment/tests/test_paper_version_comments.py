from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APITestCase

from paper.related_models.paper_version import PaperVersion
from paper.tests.helpers import create_paper
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from researchhub_comment.views.rh_comment_view import RhCommentViewSet
from user.tests.helpers import create_random_default_user


class PaperVersionCommentsTests(APITestCase):
    def setUp(self):
        """Set up test data for paper version comment tests."""
        self.user = create_random_default_user("test_user")

        # Create original paper
        self.original_paper = create_paper(title="Original Paper")

        # Create version 1
        self.version_1_paper = create_paper(title="Paper Version 1")
        self.version_1 = PaperVersion.objects.create(
            paper=self.version_1_paper,
            version=1,
            base_doi="10.1234/test",
            message="First version",
            original_paper=self.original_paper,
            publication_status=PaperVersion.PREPRINT,
        )

        # Create version 2
        self.version_2_paper = create_paper(title="Paper Version 2")
        self.version_2 = PaperVersion.objects.create(
            paper=self.version_2_paper,
            version=2,
            base_doi="10.1234/test",
            message="Second version",
            original_paper=self.original_paper,
            publication_status=PaperVersion.PUBLISHED,
        )

    def _create_comment_thread(self, paper, thread_type="GENERIC_COMMENT"):
        """Helper method to create a comment thread for a paper."""
        content_type = ContentType.objects.get_for_model(paper)
        thread = RhCommentThreadModel.objects.create(
            content_type=content_type,
            object_id=paper.id,
            thread_type=thread_type,
            created_by=self.user,
        )
        return thread

    def _create_comment(self, thread, text="Test comment"):
        """Helper method to create a comment in a thread."""
        comment = RhCommentModel.objects.create(
            thread=thread,
            created_by=self.user,
            comment_content_json={"ops": [{"insert": text}]},
        )
        return comment

    def test_get_model_object_threads_returns_all_version_threads(self):
        """Test that _get_model_object_threads returns threads from all paper
        versions."""
        # Create threads for each paper version
        original_thread = self._create_comment_thread(self.original_paper)
        version_1_thread = self._create_comment_thread(self.version_1_paper)
        version_2_thread = self._create_comment_thread(self.version_2_paper)

        # Create comments in each thread
        self._create_comment(original_thread, "Comment on original")
        self._create_comment(version_1_thread, "Comment on version 1")
        self._create_comment(version_2_thread, "Comment on version 2")

        # Test with original paper
        view = RhCommentViewSet()
        view.kwargs = {"model": "paper", "model_object_id": self.original_paper.id}

        threads = view._get_model_object_threads()
        thread_ids = set(threads.values_list("id", flat=True))
        expected_thread_ids = {
            original_thread.id,
            version_1_thread.id,
            version_2_thread.id,
        }

        self.assertEqual(thread_ids, expected_thread_ids)
        self.assertEqual(threads.count(), 3)

    def test_get_model_object_threads_with_version_paper_id(self):
        """Test that _get_model_object_threads works when called with a version
        paper ID."""
        # Create threads for each paper version
        original_thread = self._create_comment_thread(self.original_paper)
        version_1_thread = self._create_comment_thread(self.version_1_paper)
        version_2_thread = self._create_comment_thread(self.version_2_paper)

        # Test with version 1 paper ID
        view = RhCommentViewSet()
        view.kwargs = {"model": "paper", "model_object_id": self.version_1_paper.id}

        threads = view._get_model_object_threads()
        thread_ids = set(threads.values_list("id", flat=True))
        expected_thread_ids = {
            original_thread.id,
            version_1_thread.id,
            version_2_thread.id,
        }

        self.assertEqual(thread_ids, expected_thread_ids)
        self.assertEqual(threads.count(), 3)

    def test_get_model_object_threads_single_paper_no_versions(self):
        """Test _get_model_object_threads with a standalone paper (no versions)."""
        standalone_paper = create_paper(title="Standalone Paper")
        standalone_thread = self._create_comment_thread(standalone_paper)

        view = RhCommentViewSet()
        view.kwargs = {"model": "paper", "model_object_id": standalone_paper.id}

        threads = view._get_model_object_threads()
        thread_ids = set(threads.values_list("id", flat=True))
        expected_thread_ids = {standalone_thread.id}

        self.assertEqual(thread_ids, expected_thread_ids)
        self.assertEqual(threads.count(), 1)

    def test_api_endpoint_returns_comments_from_all_versions(self):
        """Test the actual API endpoint returns comments from all paper
        versions."""
        # Create threads and comments for each paper version
        original_thread = self._create_comment_thread(self.original_paper)
        version_1_thread = self._create_comment_thread(self.version_1_paper)
        version_2_thread = self._create_comment_thread(self.version_2_paper)

        original_comment = self._create_comment(original_thread, "Comment on original")
        version_1_comment = self._create_comment(
            version_1_thread, "Comment on version 1"
        )
        version_2_comment = self._create_comment(
            version_2_thread, "Comment on version 2"
        )

        # Make API request to get comments for original paper
        self.client.force_authenticate(self.user)
        response = self.client.get(f"/api/paper/{self.original_paper.id}/comments/")

        self.assertEqual(response.status_code, 200)

        # Should return comments from all versions
        comment_ids = {comment["id"] for comment in response.data["results"]}
        expected_comment_ids = {
            original_comment.id,
            version_1_comment.id,
            version_2_comment.id,
        }

        self.assertEqual(comment_ids, expected_comment_ids)
        self.assertEqual(response.data["count"], 3)

    def test_api_endpoint_with_version_paper_id(self):
        """Test the API endpoint works when called with a version paper ID."""
        # Create threads and comments for each paper version
        original_thread = self._create_comment_thread(self.original_paper)
        version_1_thread = self._create_comment_thread(self.version_1_paper)
        version_2_thread = self._create_comment_thread(self.version_2_paper)

        original_comment = self._create_comment(original_thread, "Comment on original")
        version_1_comment = self._create_comment(
            version_1_thread, "Comment on version 1"
        )
        version_2_comment = self._create_comment(
            version_2_thread, "Comment on version 2"
        )

        # Make API request to get comments for version 1 paper
        self.client.force_authenticate(self.user)
        response = self.client.get(f"/api/paper/{self.version_1_paper.id}/comments/")

        self.assertEqual(response.status_code, 200)

        # Should return comments from all versions
        comment_ids = {comment["id"] for comment in response.data["results"]}
        expected_comment_ids = {
            original_comment.id,
            version_1_comment.id,
            version_2_comment.id,
        }

        self.assertEqual(comment_ids, expected_comment_ids)
        self.assertEqual(response.data["count"], 3)

    def test_comments_from_different_paper_families_not_mixed(self):
        """Test that comments from different paper families are not mixed."""
        # Create a completely separate paper family
        other_original = create_paper(title="Other Original Paper")
        other_version_paper = create_paper(title="Other Version Paper")
        PaperVersion.objects.create(
            paper=other_version_paper,
            version=1,
            base_doi="10.9999/other",
            message="Other version",
            original_paper=other_original,
            publication_status=PaperVersion.PREPRINT,
        )

        # Create threads and comments for our original paper family
        original_thread = self._create_comment_thread(self.original_paper)
        version_1_thread = self._create_comment_thread(self.version_1_paper)

        # Create threads and comments for the other paper family
        other_original_thread = self._create_comment_thread(other_original)
        other_version_thread = self._create_comment_thread(other_version_paper)

        our_comment = self._create_comment(original_thread, "Our comment")
        our_version_comment = self._create_comment(
            version_1_thread, "Our version comment"
        )
        other_comment = self._create_comment(other_original_thread, "Other comment")
        other_version_comment = self._create_comment(
            other_version_thread, "Other version comment"
        )

        # Get comments for our paper family
        self.client.force_authenticate(self.user)
        response = self.client.get(f"/api/paper/{self.original_paper.id}/comments/")

        self.assertEqual(response.status_code, 200)

        # Should only return comments from our paper family
        comment_ids = {comment["id"] for comment in response.data["results"]}
        expected_comment_ids = {our_comment.id, our_version_comment.id}
        unexpected_comment_ids = {other_comment.id, other_version_comment.id}

        self.assertEqual(comment_ids, expected_comment_ids)
        self.assertTrue(comment_ids.isdisjoint(unexpected_comment_ids))
        self.assertEqual(response.data["count"], 2)
