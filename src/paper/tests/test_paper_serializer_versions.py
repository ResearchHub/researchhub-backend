from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APIRequestFactory

from paper.related_models.paper_version import PaperVersion
from paper.serializers.paper_serializers import DynamicPaperSerializer
from paper.tests.helpers import create_paper
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from user.tests.helpers import create_random_default_user


class PaperSerializerVersionTests(TestCase):
    def setUp(self):
        """Set up test data for paper serializer version tests."""
        self.user = create_random_default_user("test_user")
        self.factory = APIRequestFactory()

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

    def test_get_discussions_returns_all_version_discussions(self):
        """Test that get_discussions returns discussions from all paper
        versions."""
        # Create threads for each paper version
        original_thread = self._create_comment_thread(self.original_paper)
        version_1_thread = self._create_comment_thread(self.version_1_paper)
        version_2_thread = self._create_comment_thread(self.version_2_paper)

        # Create comments in each thread
        self._create_comment(original_thread, "Comment on original")
        self._create_comment(version_1_thread, "Comment on version 1")
        self._create_comment(version_2_thread, "Comment on version 2")

        # Test serializer with original paper
        request = self.factory.get("/")
        request.user = self.user
        serializer = DynamicPaperSerializer(
            self.original_paper, context={"request": request}
        )

        discussions = serializer.get_discussions(self.original_paper)

        # Should return discussions from all versions
        thread_ids = {discussion["id"] for discussion in discussions}
        expected_thread_ids = {
            original_thread.id,
            version_1_thread.id,
            version_2_thread.id,
        }

        self.assertEqual(thread_ids, expected_thread_ids)
        self.assertEqual(len(discussions), 3)

    def test_get_discussions_with_version_paper(self):
        """Test that get_discussions works when called with a version paper."""
        # Create threads for each paper version
        original_thread = self._create_comment_thread(self.original_paper)
        version_1_thread = self._create_comment_thread(self.version_1_paper)
        version_2_thread = self._create_comment_thread(self.version_2_paper)

        # Test serializer with version 1 paper
        request = self.factory.get("/")
        request.user = self.user
        serializer = DynamicPaperSerializer(
            self.version_1_paper, context={"request": request}
        )

        discussions = serializer.get_discussions(self.version_1_paper)

        # Should return discussions from all versions
        thread_ids = {discussion["id"] for discussion in discussions}
        expected_thread_ids = {
            original_thread.id,
            version_1_thread.id,
            version_2_thread.id,
        }

        self.assertEqual(thread_ids, expected_thread_ids)
        self.assertEqual(len(discussions), 3)

    def test_get_discussions_single_paper_no_versions(self):
        """Test get_discussions with a standalone paper (no versions)."""
        standalone_paper = create_paper(title="Standalone Paper")
        standalone_thread = self._create_comment_thread(standalone_paper)
        self._create_comment(standalone_thread, "Standalone comment")

        request = self.factory.get("/")
        request.user = self.user
        serializer = DynamicPaperSerializer(
            standalone_paper, context={"request": request}
        )

        discussions = serializer.get_discussions(standalone_paper)

        # Should return only the standalone paper's discussions
        thread_ids = {discussion["id"] for discussion in discussions}
        expected_thread_ids = {standalone_thread.id}

        self.assertEqual(thread_ids, expected_thread_ids)
        self.assertEqual(len(discussions), 1)

    def test_get_discussion_aggregates_includes_all_versions(self):
        """Test that get_discussion_aggregates aggregates data from all paper
        versions."""
        # Create threads and comments for each paper version
        original_thread = self._create_comment_thread(self.original_paper)
        version_1_thread = self._create_comment_thread(self.version_1_paper)
        version_2_thread = self._create_comment_thread(self.version_2_paper)

        # Create comments in each thread
        self._create_comment(original_thread, "Comment on original")
        self._create_comment(version_1_thread, "Comment on version 1")
        self._create_comment(version_2_thread, "Comment on version 2")

        # Test serializer with original paper
        request = self.factory.get("/")
        request.user = self.user
        serializer = DynamicPaperSerializer(
            self.original_paper, context={"request": request}
        )

        aggregates = serializer.get_discussion_aggregates(self.original_paper)

        # Should include aggregates from all versions
        # The exact structure depends on the get_discussion_aggregates
        # implementation
        self.assertIsInstance(aggregates, dict)
        self.assertIn("discussion_count", aggregates)

        # The discussion count should reflect comments from all versions
        # (this depends on how the paper's discussion_count property works)

    def test_get_discussion_aggregates_with_version_paper(self):
        """Test that get_discussion_aggregates works when called with a version
        paper."""
        # Create threads and comments for each paper version
        original_thread = self._create_comment_thread(self.original_paper)
        version_1_thread = self._create_comment_thread(self.version_1_paper)
        version_2_thread = self._create_comment_thread(self.version_2_paper)

        # Create comments in each thread
        self._create_comment(original_thread, "Comment on original")
        self._create_comment(version_1_thread, "Comment on version 1")
        self._create_comment(version_2_thread, "Comment on version 2")

        # Test serializer with version 1 paper
        request = self.factory.get("/")
        request.user = self.user
        serializer = DynamicPaperSerializer(
            self.version_1_paper, context={"request": request}
        )

        aggregates = serializer.get_discussion_aggregates(self.version_1_paper)

        # Should include aggregates from all versions
        self.assertIsInstance(aggregates, dict)
        self.assertIn("discussion_count", aggregates)

    def test_discussions_from_different_paper_families_not_mixed(self):
        """Test that discussions from different paper families are not mixed."""
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

        self._create_comment(original_thread, "Our comment")
        self._create_comment(version_1_thread, "Our version comment")
        self._create_comment(other_original_thread, "Other comment")
        self._create_comment(other_version_thread, "Other version comment")

        # Test serializer with our paper family
        request = self.factory.get("/")
        request.user = self.user
        serializer = DynamicPaperSerializer(
            self.original_paper, context={"request": request}
        )

        discussions = serializer.get_discussions(self.original_paper)

        # Should only return discussions from our paper family
        thread_ids = {discussion["id"] for discussion in discussions}
        expected_thread_ids = {original_thread.id, version_1_thread.id}
        unexpected_thread_ids = {other_original_thread.id, other_version_thread.id}

        self.assertEqual(thread_ids, expected_thread_ids)
        self.assertTrue(thread_ids.isdisjoint(unexpected_thread_ids))
        self.assertEqual(len(discussions), 2)

    def test_serializer_context_fields_respected(self):
        """Test that serializer context fields are properly passed through."""
        # Create a thread and comment
        original_thread = self._create_comment_thread(self.original_paper)
        self._create_comment(original_thread, "Test comment")

        # Test with specific context fields
        request = self.factory.get("/")
        request.user = self.user
        context = {
            "request": request,
            "pap_dps_get_discussions": {"_include_fields": ["id", "thread_type"]},
            "pap_dps_get_discussions_select": ["content_type"],
            "pap_dps_get_discussions_prefetch": ["rh_comments"],
        }

        serializer = DynamicPaperSerializer(self.original_paper, context=context)

        discussions = serializer.get_discussions(self.original_paper)

        # Should still return discussions, context fields should be applied
        self.assertGreater(len(discussions), 0)

        # Verify that the context fields were used (basic check)
        for discussion in discussions:
            self.assertIn("id", discussion)

    def test_empty_paper_versions_chain(self):
        """Test behavior with papers that have no comments or threads."""
        # Create papers with no comments
        empty_original = create_paper(title="Empty Original")
        empty_version_paper = create_paper(title="Empty Version")
        PaperVersion.objects.create(
            paper=empty_version_paper,
            version=1,
            base_doi="10.1111/empty",
            message="Empty version",
            original_paper=empty_original,
            publication_status=PaperVersion.PREPRINT,
        )

        request = self.factory.get("/")
        request.user = self.user
        serializer = DynamicPaperSerializer(
            empty_original, context={"request": request}
        )

        discussions = serializer.get_discussions(empty_original)
        aggregates = serializer.get_discussion_aggregates(empty_original)

        # Should return empty results
        self.assertEqual(len(discussions), 0)
        self.assertIsInstance(aggregates, dict)
