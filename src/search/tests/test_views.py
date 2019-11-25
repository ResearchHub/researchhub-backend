from unittest import skip
from django.test import TestCase

from discussion.tests.helpers import create_thread
from paper.tests.helpers import create_paper
from user.tests.helpers import create_random_authenticated_user
from utils.test_helpers import (
    TestData,
    get_authenticated_get_response
)


@skip('Until we have an ElasticSearch test instance')
class SearchViewsTests(TestCase):

    def setUp(self):
        self.base_url = '/api/search/'
        self.user = create_random_authenticated_user('search_views')
        create_papers(10)
        create_threads(10, self.user)

    def test_get_all_papers(self):
        url = self.base_url + 'papers/'
        response = self.get_search_response(url)
        self.assertEqual(response.status_code, 200)
        # self.assertContains(response, 'count', status_code=200)

    # def test_search_paper_by_id(self):
    #     url = self.base_url + 'papers/?ids=1'
    #     resp = self.get_search_response(url)
    #     resp_content = bytes_to_json(resp.content)
    #     number_of_results = resp_content['count']
    #     self.assertEqual(number_of_results, 1)

    # def test_search_thread_by_id(self):
    #     url = self.base_url + 'threads/?ids=1'
    #     resp = self.get_search_response(url)
    #     resp_content = bytes_to_json(resp.content)
    #     number_of_results = resp_content['count']
    #     self.assertEqual(number_of_results, 1)

    # def test_or_filter(self):
    #     url = self.base_url + 'threads/?ids=1|2|3'
    #     resp = self.get_search_response(url)
    #     resp_content = bytes_to_json(resp.content)
    #     number_of_results = resp_content['count']
    #     self.assertEqual(number_of_results, 3)

    def get_search_response(self, url):
        return get_authenticated_get_response(
            self.user,
            url
        )


def create_papers(amount, uploaded_by=None):
    for i in range(amount):
        title = TestData.paper_titles[i]
        create_paper(title=title, uploaded_by=uploaded_by)


def create_threads(amount, created_by):
    for i in range(amount):
        create_thread(title=f'Thread Title {i}', created_by=created_by)
