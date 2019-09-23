from django.test import TestCase

from utils.test_helpers import IntegrationTestHelper, TestHelper


class PaperTests(TestCase, TestHelper):

    def test_string_representation(self):
        paper = self.create_paper_without_authors()
        text = '%s: []' % self.test_data.paper_title
        self.assertEqual(str(paper), text)


class PaperIntegrationTests(TestCase, IntegrationTestHelper):
    base_url = '/api/paper/'

    def test_get_base_route(self):
        response = self.get_get_response(self.base_url)
        self.assertEqual(response.status_code, 200)

    def test_upload_paper(self):
        response = self.submit_paper_form()
        text = self.paper_title
        self.assertContains(response, text, status_code=201)

    def submit_paper_form(self):
        client = self.get_default_authenticated_client()
        url = self.base_url
        form_data = self.build_default_paper_form()
        response = client.post(url, form_data)
        return response

    def build_default_paper_form(self):
        title = self.paper_title
        form = {
            'title': title,
            'paper_publish_date': self.paper_publish_date
        }
        return form
