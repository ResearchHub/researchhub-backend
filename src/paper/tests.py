from django.test import TestCase

from utils.test_helpers import TestHelper


class PaperTests(TestCase, TestHelper):

    def test_string_representation(self):
        paper = self.create_paper_without_authors()
        text = '%s: []' % self.test_data.paper_title
        self.assertEqual(str(paper), text)
