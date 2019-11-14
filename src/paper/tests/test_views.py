import random

from django.test import TestCase

from .helpers import create_flag, create_paper
from user.tests.helpers import (
    create_random_authenticated_user,
    create_random_authenticated_user_with_reputation
)
from utils.test_helpers import (
    get_authenticated_post_response,
    get_authenticated_delete_response,
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

    # Need to fix this so they don't redirect
    # def test_check_url_is_true_if_url_has_pdf(self):
    #     url = self.base_url + 'check_url'
    #     data = {'url': 'https://bitcoin.org/bitcoin.pdf'}
    #     response = get_authenticated_post_response(self.user, url, data)
    #     self.assertContains(response, 'True', status_code=200)

    # def test_check_url_is_false_if_url_does_NOT_have_pdf(self):
    #     url = self.base_url + 'check_url'
    #     data = {'url': 'https://bitcoin.org/en/'}
    #     response = get_authenticated_post_response(self.user, url, data)
    #     self.assertContains(response, 'False', status_code=200)

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
