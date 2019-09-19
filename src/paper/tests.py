from django.test import TestCase

from utils.test_helpers import IntegrationTestHelper, TestHelper


class PaperTests(TestCase, TestHelper):

    def test_string_representation(self):
        paper = self.create_paper_without_authors()
        text = '%s: []' % self.test_data.paper_title
        self.assertEqual(str(paper), text)


class PaperIntegrationTests(TestCase, IntegrationTestHelper):

    def test_get_base_route(self):
        url = '/api/paper/'
        response = self.get_response(url)
        self.assertEqual(response.status_code, 200)
