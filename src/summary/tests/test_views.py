from django.test import TestCase

from user.tests.helpers import create_random_authenticated_user
from utils.test_helpers import get_authenticated_post_response


class SummaryViewsTests(TestCase):

    def setUp(self):
        self.user = create_random_authenticated_user('summary_views')

    def test_post_propose_edit_route_gives_405(self):
        # Because you can't post to a detail route
        response = self.get_propose_edit_post_response(self.user)
        self.assertEqual(response.status_code, 405)

    def get_propose_edit_post_response(self, user):
        url = '/api/summary/propose_edit/'
        data = None
        return get_authenticated_post_response(
            user,
            url,
            data,
            content_type='application/json'
        )
