from unittest import TestCase
from unittest.mock import Mock, patch

from search.utils import bulk_remove_from_search_index, remove_from_search_index


class TestRemoveFromSearchIndex(TestCase):

    @patch("search.utils.registry")
    def test_deletes_from_each_registered_document(self, mock_registry):
        doc1 = Mock()
        doc2 = Mock()
        mock_registry._models.get.return_value = {doc1, doc2}

        instance = Mock(pk=1)
        remove_from_search_index(instance)

        doc1().update.assert_called_once_with(instance, "delete")
        doc2().update.assert_called_once_with(instance, "delete")

    @patch("search.utils.registry")
    def test_noop_for_unregistered_model(self, mock_registry):
        mock_registry._models.get.return_value = set()

        remove_from_search_index(Mock(pk=1))

    @patch("search.utils.registry")
    def test_continues_on_error(self, mock_registry):
        doc1 = Mock()
        doc2 = Mock()
        doc1().update.side_effect = Exception("connection error")
        mock_registry._models.get.return_value = {doc1, doc2}

        instance = Mock(pk=1)
        remove_from_search_index(instance)

        doc2().update.assert_called_once_with(instance, "delete")


class TestBulkRemoveFromSearchIndex(TestCase):

    @patch("search.utils.remove_from_search_index")
    def test_removes_each_instance(self, mock_remove):
        instance1 = Mock(pk=1)
        instance2 = Mock(pk=2)

        qs = Mock()
        qs.iterator.return_value = iter([instance1, instance2])

        bulk_remove_from_search_index(qs)

        self.assertEqual(mock_remove.call_count, 2)
        mock_remove.assert_any_call(instance1)
        mock_remove.assert_any_call(instance2)

    @patch("search.utils.remove_from_search_index")
    def test_handles_empty_queryset(self, mock_remove):
        qs = Mock()
        qs.iterator.return_value = iter([])

        bulk_remove_from_search_index(qs)

        mock_remove.assert_not_called()
