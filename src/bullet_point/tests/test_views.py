from django.test import TestCase

from bullet_point.tests.helpers import create_bullet_point
from paper.tests.helpers import create_paper
from user.tests.helpers import create_random_authenticated_user
from utils.test_helpers import (
    get_authenticated_delete_response,
    get_authenticated_patch_response,
    get_authenticated_post_response,
    get_authenticated_put_response
)


class BulletPointViewsTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user('BP')
        self.base_url = '/api/bullet_point/'
        self.paper = create_paper()
        self.bullet_point = create_bullet_point(
            paper=self.paper,
            created_by=self.user
        )

    def test_user_can_update_ordinal(self):
        data = {'ordinal': 1}
        response = self.get_patch_response(
            self.user,
            self.bullet_point.id,
            data
        )
        self.assertContains(response, 'ordinal":1', status_code=200)

    def get_delete_response(self, user, bullet_point_id):
        url = self.base_url + str(bullet_point_id) + '/'
        data = None
        return get_authenticated_delete_response(
            user,
            url,
            data,
            content_type='application/json'
        )

    def get_lock_ordinal_response(self, user, bullet_point_id, lock=True):
        data = {'ordinal_is_locked': lock}
        return self.get_patch_response(
            user,
            bullet_point_id,
            data
        )

    def get_remove_response(self, user, bullet_point_id, remove=True):
        data = {'is_removed': remove}
        return self.get_patch_response(
            user,
            bullet_point_id,
            data
        )

    def get_patch_response(self, user, bullet_point_id, data):
        url = self.base_url + str(bullet_point_id) + '/'
        response = get_authenticated_patch_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response

    def get_post_response(self, user, data=None):
        url = self.base_url
        if data is None:
            data = {
                'paper': self.paper.id,
                'text': 'Hello, world',
                'plain_text': 'Hello, world'
            }
        response = get_authenticated_post_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response

    def get_put_response(self, user, bullet_point_id):
        url = self.base_url + str(bullet_point_id) + '/'
        data = {}
        response = get_authenticated_put_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response
