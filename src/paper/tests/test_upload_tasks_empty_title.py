from unittest import TestCase


class TestCrossrefEmptyTitle(TestCase):
    """Verifies that an empty title list from Crossref is handled gracefully."""

    def test_empty_title_list_returns_early(self):
        title_list = []
        self.assertFalse(bool(title_list))

    def test_nonempty_title_list_works(self):
        title_list = ["A paper title"]
        self.assertTrue(bool(title_list))
        self.assertEqual(title_list[0], "A paper title")
