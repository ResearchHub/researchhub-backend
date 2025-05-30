from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from paper.related_models.paper_version import PaperSeries, PaperVersion
from paper.tests.helpers import create_paper
from researchhub_comment.constants.rh_comment_thread_types import GENERIC_COMMENT
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from user.tests.helpers import create_random_default_user


class PaperVersionDiscussionCountTests(TestCase):
    def setUp(self):
        """Set up test data for paper version discussion count tests."""
        self.user = create_random_default_user("test_user")

        # Create paper series
        self.paper_series = PaperSeries.objects.create()

        # Create version 1
        self.version_1_paper = create_paper(title="Paper Version 1")
        self.version_1_paper.paper_series = self.paper_series
        self.version_1_paper.save()

        self.version_1 = PaperVersion.objects.create(
            paper=self.version_1_paper,
            version=1,
            base_doi="10.1234/test",
            message="First version",
            original_paper=self.version_1_paper,
            publication_status=PaperVersion.PREPRINT,
        )

        # Create version 2
        self.version_2_paper = create_paper(title="Paper Version 2")
        self.version_2_paper.paper_series = self.paper_series
        self.version_2_paper.save()

        self.version_2 = PaperVersion.objects.create(
            paper=self.version_2_paper,
            version=2,
            base_doi="10.1234/test",
            message="Second version",
            original_paper=self.version_1_paper,
            publication_status=PaperVersion.PUBLISHED,
        )

    def _create_comment_thread_and_comments(self, paper, num_comments=1):
        """Helper method to create a comment thread and comments for a paper."""
        content_type = ContentType.objects.get_for_model(paper)
        thread = RhCommentThreadModel.objects.create(
            content_type=content_type,
            object_id=paper.id,
            thread_type=GENERIC_COMMENT,
            created_by=self.user,
        )

        comments = []
        for i in range(num_comments):
            comment = RhCommentModel.objects.create(
                thread=thread,
                comment_content_json={"ops": [{"insert": f"Test comment {i+1}"}]},
                created_by=self.user,
            )
            comments.append(comment)

        return thread, comments

    def test_discussion_count_single_paper_no_versions(self):
        """Test discussion count for a paper with no versions."""
        # Create a standalone paper (not part of any series)
        standalone_paper = create_paper(title="Standalone Paper")

        # Create comments on the standalone paper
        self._create_comment_thread_and_comments(standalone_paper, 3)

        # Discussion count should only include comments from this paper
        self.assertEqual(standalone_paper.get_discussion_count(), 3)

    def test_discussion_count_paper_with_versions(self):
        """Test discussion count for papers that are part of a version series."""
        # Create comments on version 1
        self._create_comment_thread_and_comments(self.version_1_paper, 3)

        # Create comments on version 2
        self._create_comment_thread_and_comments(self.version_2_paper, 1)

        # Each paper should return the total count from all versions (3 + 1 = 4)
        self.assertEqual(self.version_1_paper.get_discussion_count(), 4)
        self.assertEqual(self.version_2_paper.get_discussion_count(), 4)

    def test_discussion_count_fallback_on_error(self):
        """Test that the method falls back to original behavior on error."""
        # Create a paper with paper_series but simulate an error condition
        paper_with_series = create_paper(title="Paper with Series")
        paper_with_series.paper_series = self.paper_series
        paper_with_series.save()

        # Create comments on this paper
        self._create_comment_thread_and_comments(paper_with_series, 2)

        # Mock the PaperService to raise an exception
        import unittest.mock

        mock_path = "paper.services.paper_version_service.PaperService"
        with unittest.mock.patch(mock_path) as mock_service:
            mock_service.side_effect = Exception("Simulated error")

            # Should fall back to original behavior (counting only this paper's threads)
            discussion_count = paper_with_series.get_discussion_count()
            # This should still work because it falls back to
            # self.rh_threads.get_discussion_count()
            self.assertEqual(discussion_count, 2)
