import random

from django.test import TestCase

from paper.tests.helpers import create_flag, create_paper, upvote_paper
from user.tests.helpers import (
    create_random_authenticated_user,
    create_random_authenticated_user_with_reputation
)
from utils.test_helpers import (
    get_authenticated_post_response,
    get_authenticated_delete_response
)


class PaperViewsTests(TestCase):

    def setUp(self):
        SEED = 'paper'
        self.random_generator = random.Random(SEED)
        self.base_url = '/api/paper/'
        self.paper = create_paper()
        self.user = create_random_authenticated_user('paper_views_user')
        self.trouble_maker = create_random_authenticated_user('trouble_maker')
        self.flag = create_flag(created_by=self.user, paper=self.paper)
        self.flag_reason = 'Inappropriate'

    def test_can_bookmark_paper(self):
        response = self.get_bookmark_post_response(self.user)
        self.assertContains(response, self.paper.title, status_code=201)

    def test_can_delete_bookmark(self):
        response = self.get_bookmark_delete_response(self.user)
        self.assertContains(response, self.paper.id, status_code=200)

    def test_can_delete_flag(self):
        response = self.get_flag_delete_response(self.user)
        self.assertContains(response, self.flag.id, status_code=200)

    def test_can_delete_flag_without_minimum_reputation(self):
        user = create_random_authenticated_user_with_reputation(49, 49)
        flag = create_flag(created_by=user, paper=self.paper)
        response = self.get_flag_delete_response(user)
        self.assertContains(response, flag.id, status_code=200)

    def test_can_ONLY_delete_own_flag(self):
        response = self.get_flag_delete_response(self.trouble_maker)
        self.assertEqual(response.status_code, 400)

    def test_delete_flag_responds_400_if_request_user_has_no_flag(self):
        pass

    def test_can_delete_vote(self):
        user = create_random_authenticated_user('deleting vote')
        vote = upvote_paper(self.paper, user)
        response = self.get_vote_delete_response(user)
        self.assertContains(response, vote.id, status_code=200)

    def test_check_url_is_true_if_url_has_pdf(self):
        url = self.base_url + 'check_url/'
        data = {'url': 'https://bitcoin.org/bitcoin.pdf'}
        response = get_authenticated_post_response(self.user, url, data)
        self.assertContains(response, 'true', status_code=200)

    def test_check_url_is_false_if_url_does_NOT_have_pdf(self):
        url = self.base_url + 'check_url/'
        data = {'url': 'https://bitcoin.org/en/'}
        response = get_authenticated_post_response(self.user, url, data)
        self.assertContains(response, 'false', status_code=200)

    def test_check_url_is_false_for_malformed_url(self):
        url = self.base_url + 'check_url/'
        data = {'url': 'bitcoin.org/bitcoin.pdf/'}
        response = get_authenticated_post_response(self.user, url, data)
        self.assertContains(response, 'false', status_code=200)

        data = {'url': 'bitcoin'}
        response = get_authenticated_post_response(self.user, url, data)
        self.assertContains(response, 'false', status_code=200)

    def test_search_by_url_arxiv(self):
        url = self.base_url + 'search_by_url/'
        data = {'url': 'https://arxiv.org/abs/1407.3561v1', 'search': True}
        response = get_authenticated_post_response(self.user, url, data)
        self.assertEquals(response.status_code, 200)
        result = response.data
        self.assertEquals(result['url'], data['url'])
        self.assertFalse(result['url_is_pdf'])
        self.assertEquals(
            result['csl_item']['title'],
            "IPFS - Content Addressed, Versioned, P2P File System")
        self.assertEqual(
            result['oa_pdf_location']['url_for_pdf'],
            'https://arxiv.org/pdf/1407.3561v1.pdf')
        self.assertIsInstance(result['search'], list)

    def test_search_by_url_arxiv_pdf(self):
        url = self.base_url + 'search_by_url/'
        data = {'url': 'https://arxiv.org/pdf/1407.3561.pdf'}
        response = get_authenticated_post_response(self.user, url, data)
        self.assertEquals(response.status_code, 200)
        result = response.data
        self.assertEquals(result['url'], data['url'])
        self.assertTrue(result['url_is_pdf'])
        self.assertFalse(result['url_is_unsupported_pdf'])
        self.assertEquals(
            result['csl_item']['title'],
            "IPFS - Content Addressed, Versioned, P2P File System")
        pdf_location = result['oa_pdf_location']
        self.assertEqual(
            pdf_location['url_for_pdf'],
            'https://arxiv.org/pdf/1407.3561.pdf')
        self.assertEqual(pdf_location['license'], 'cc-by')
        self.assertEqual(
            pdf_location['url_for_landing_page'],
            'https://arxiv.org/abs/1407.3561')
        self.assertFalse('search' in result)

    def test_search_by_url_publisher(self):
        url = self.base_url + 'search_by_url/'
        data = {'url': 'https://www.nature.com/articles/s41586-019-1099-1'}
        response = get_authenticated_post_response(self.user, url, data)
        self.assertEquals(response.status_code, 200)
        result = response.data
        self.assertEquals(result['url'], data['url'])
        self.assertFalse(result['url_is_pdf'])
        self.assertFalse(result['url_is_unsupported_pdf'])
        self.assertEquals(
            result['csl_item']['title'],
            "Restoration of brain circulation and cellular functions hours post-mortem")  # noqa E501
        self.assertEquals(
            result['csl_item']['DOI'], "10.1038/s41586-019-1099-1")

    def test_search_by_url_doi(self):
        url = self.base_url + 'search_by_url/'
        data = {'url': 'https://doi.org/10.1038/ng.3259'}
        response = get_authenticated_post_response(self.user, url, data)
        self.assertEquals(response.status_code, 200)
        result = response.data
        self.assertEquals(result['url'], data['url'])
        self.assertFalse(result['url_is_pdf'])
        self.assertFalse(result['url_is_unsupported_pdf'])
        self.assertEquals(
            result['csl_item']['title'],
            "Understanding multicellular function and disease with human tissue-specific networks")  # noqa E501
        self.assertEquals(
            result['csl_item']['DOI'], "10.1038/ng.3259")
        self.assertEquals(
            result['oa_pdf_location']['url_for_pdf'],
            "http://europepmc.org/articles/pmc4828725?pdf=render")

    def test_search_by_url_pmid(self):
        """
        Search by PMID without a DOI from an inactive journal
        """
        url = self.base_url + 'search_by_url/'
        data = {'url': 'https://www.ncbi.nlm.nih.gov/pubmed/18888140'}
        response = get_authenticated_post_response(self.user, url, data)
        self.assertEquals(response.status_code, 200)
        result = response.data
        self.assertEquals(result['url'], data['url'])
        self.assertFalse(result['url_is_pdf'])
        self.assertFalse(result['url_is_unsupported_pdf'])
        self.assertEquals(
            result['csl_item']['title'],
            "[Major achievements in the second plan year in the Soviet Union].")  # noqa E501
        self.assertIsNone(result['oa_pdf_location'])

    def test_search_by_url_unsupported_pdf(self):
        url = self.base_url + 'search_by_url/'
        data = {'url': 'https://bitcoin.org/bitcoin.pdf'}
        response = get_authenticated_post_response(self.user, url, data)
        self.assertEquals(response.status_code, 200)
        result = response.data
        self.assertTrue(result['url_is_pdf'])
        self.assertTrue(result['url_is_unsupported_pdf'])
        self.assertEqual(result['csl_item']['URL'], data['url'])
        self.assertEqual(result['oa_pdf_location']['url_for_pdf'], data['url'])

    def test_search_by_url_bad(self):
        url = self.base_url + 'search_by_url/'
        data = {'url': 'org/this-is-a-bad-url'}
        response = get_authenticated_post_response(self.user, url, data)
        self.assertContains(response, 'Double check that URL', status_code=400)

    def get_bookmark_post_response(self, user):
        url = self.base_url + f'{self.paper.id}/bookmark/'
        data = None
        response = get_authenticated_post_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response

    def get_bookmark_delete_response(self, user):
        url = self.base_url + f'{self.paper.id}/bookmark/'
        data = None
        response = get_authenticated_delete_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response

    def get_flag_delete_response(self, user):
        url = self.base_url + f'{self.paper.id}/flag/'
        data = None
        response = get_authenticated_delete_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response

    def get_vote_delete_response(self, user):
        url = self.base_url + f'{self.paper.id}/user_vote/'
        data = {}
        response = get_authenticated_delete_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response
