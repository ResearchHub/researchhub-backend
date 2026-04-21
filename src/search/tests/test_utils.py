from unittest import TestCase
from unittest.mock import Mock, call, patch

from search.utils import sync_search_index


class TestSyncSearchIndex(TestCase):

    @patch("search.utils.registry")
    def test_calls_registry_update_for_each_instance(self, mock_registry):
        instance1 = Mock(pk=1)
        instance2 = Mock(pk=2)
        instance3 = Mock(pk=3)

        qs = Mock()
        qs.iterator.return_value = iter([instance1, instance2, instance3])

        sync_search_index(qs)

        mock_registry.update.assert_has_calls(
            [call(instance1), call(instance2), call(instance3)]
        )
        self.assertEqual(mock_registry.update.call_count, 3)

    @patch("search.utils.registry")
    def test_handles_empty_queryset(self, mock_registry):
        qs = Mock()
        qs.iterator.return_value = iter([])

        sync_search_index(qs)

        mock_registry.update.assert_not_called()

    @patch("search.utils.registry")
    def test_continues_on_error(self, mock_registry):
        instance1 = Mock(pk=1)
        instance2 = Mock(pk=2)
        instance3 = Mock(pk=3)

        qs = Mock()
        qs.iterator.return_value = iter([instance1, instance2, instance3])

        mock_registry.update.side_effect = [
            None,
            Exception("OpenSearch connection error"),
            None,
        ]

        sync_search_index(qs)

        self.assertEqual(mock_registry.update.call_count, 3)
