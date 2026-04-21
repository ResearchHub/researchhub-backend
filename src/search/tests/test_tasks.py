from unittest import TestCase
from unittest.mock import Mock, patch

from search.tasks import cleanup_removed_content_from_search_index


class TestCleanupRemovedContentTask(TestCase):

    @patch("search.tasks.sync_search_index")
    def test_syncs_removed_papers_and_posts(self, mock_sync):
        with patch(
            "search.tasks.Paper"
        ) as MockPaper, patch(
            "search.tasks.ResearchhubPost"
        ) as MockPost:
            paper_qs = MockPaper.objects.filter.return_value
            post_qs = MockPost.objects.filter.return_value

            cleanup_removed_content_from_search_index()

            MockPaper.objects.filter.assert_called_once_with(is_removed=True)
            MockPost.objects.filter.assert_called_once_with(
                unified_document__is_removed=True,
            )
            mock_sync.assert_any_call(paper_qs)
            mock_sync.assert_any_call(post_qs)
            self.assertEqual(mock_sync.call_count, 2)

    @patch("search.tasks.sync_search_index")
    def test_calls_sync_even_when_querysets_are_empty(self, mock_sync):
        with patch("search.tasks.Paper"), patch("search.tasks.ResearchhubPost"):
            cleanup_removed_content_from_search_index()

            self.assertEqual(mock_sync.call_count, 2)
