from django.test import TestCase

from .helpers import build_summary_data, create_summary
from paper.tests.helpers import create_paper
from user.tests.helpers import (
    create_random_authenticated_user,
    create_random_authenticated_user_with_reputation
)
from utils.test_helpers import (
    get_authenticated_delete_response,
    get_authenticated_patch_response,
    get_authenticated_post_response,
    get_authenticated_put_response
)


class SummaryPermissionsTests(TestCase):

    def setUp(self):
        self.base_url = '/api/summary/'
        self.user = create_random_authenticated_user('summary_user')
        self.paper = create_paper(title='Summary Permissions Tests')
        self.summary_text = 'This is a summary for the permissions tests'
        self.summary = create_summary(
            self.summary_text,
            self.user,
            self.paper.id
        )

    def test_can_propose_summary_edit_with_minimum_reputation(self):
        user = create_random_authenticated_user_with_reputation(5, 5)
        response = self.get_summary_post_response(user)
        self.assertEqual(response.status_code, 201)

    def test_can_NOT_propose_summary_edit_below_minimum_reputation(self):
        user = create_random_authenticated_user_with_reputation(4, 4)
        response = self.get_summary_post_response(user)
        self.assertEqual(response.status_code, 403)

    def test_can_patch_summary_when_user_is_proposer(self):
        user = create_random_authenticated_user_with_reputation(50, 50)
        summary = create_summary('patch summary', user, self.paper.id)
        response = self.get_summary_patch_response(user, summary=summary)
        self.assertEqual(response.status_code, 200)

    def test_can_NOT_patch_summary_when_not_proposer(self):
        user = create_random_authenticated_user_with_reputation(49, 49)
        response = self.get_summary_patch_response(user)
        self.assertEqual(response.status_code, 403)

    def test_can_put_summary_when_user_is_proposer(self):
        user = create_random_authenticated_user_with_reputation(50, 50)
        summary = create_summary('put summary', user, self.paper.id)
        response = self.get_summary_put_response(user, summary=summary)
        self.assertEqual(response.status_code, 200)

    def test_can_NOT_put_summary_when_not_proposer(self):
        user = create_random_authenticated_user_with_reputation(49, 49)
        response = self.get_summary_put_response(user)
        self.assertEqual(response.status_code, 403)

    def test_can_delete_summary_when_user_is_proposer(self):
        user = create_random_authenticated_user_with_reputation(50, 50)
        summary = create_summary('delete summary', user, self.paper.id)
        response = self.get_summary_delete_response(user, summary=summary)
        self.assertEqual(response.status_code, 204)

    def test_can_NOT_delete_summary_when_not_proposer(self):
        user = create_random_authenticated_user_with_reputation(49, 49)
        response = self.get_summary_delete_response(user)
        self.assertEqual(response.status_code, 403)

    def get_summary_post_response(self, user):
        url = self.base_url
        data = build_summary_data(self.summary_text, self.paper.id, None)
        response = get_authenticated_post_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response

    def get_summary_patch_response(self, user, summary=None):
        if summary is None:
            summary = self.summary
        url = self.base_url + f'{summary.id}/'
        data = {'summary': 'A patch update'}
        response = get_authenticated_patch_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response

    def get_summary_put_response(self, user, summary=None):
        if summary is None:
            summary = self.summary
        url = self.base_url + f'{summary.id}/'
        data = build_summary_data('A put update', self.paper.id, None)
        response = get_authenticated_put_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response

    def get_summary_delete_response(self, user, summary=None):
        if summary is None:
            summary = self.summary
        url = self.base_url + f'{summary.id}/'
        data = None
        response = get_authenticated_delete_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response
