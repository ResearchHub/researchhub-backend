from unittest import TestCase
from unittest.mock import patch

from search.tasks import cleanup_removed_content_from_search_index


class TestCleanupRemovedContentTask(TestCase):

    @patch("search.tasks.bulk_remove_from_search_index")
    @patch("paper.models.Paper.objects")
    @patch(
        "researchhub_document.related_models.researchhub_post_model"
        ".ResearchhubPost.objects"
    )
    def test_removes_papers_and_posts(
        self, mock_post_objects, mock_paper_objects, mock_bulk_remove
    ):
        paper_qs = mock_paper_objects.filter.return_value
        post_qs = mock_post_objects.filter.return_value

        cleanup_removed_content_from_search_index()

        mock_paper_objects.filter.assert_called_once_with(is_removed=True)
        mock_post_objects.filter.assert_called_once_with(
            unified_document__is_removed=True,
        )
        mock_bulk_remove.assert_any_call(paper_qs)
        mock_bulk_remove.assert_any_call(post_qs)
        self.assertEqual(mock_bulk_remove.call_count, 2)
