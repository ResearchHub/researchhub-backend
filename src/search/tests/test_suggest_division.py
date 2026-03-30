from unittest import TestCase

from search.views.suggest import SuggestView


class TestPerformRegularSearchEmptyIndexes(TestCase):
    def test_empty_indexes_returns_empty_dict(self):
        view = SuggestView()
        result = view.perform_regular_search("test query", [], 10)
        self.assertEqual(result, {})
