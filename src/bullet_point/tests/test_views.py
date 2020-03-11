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
        self.paper = create_paper()
        self.base_url = f'/api/paper/{self.paper.id}/bullet_point/'
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

    def test_edit_creates_new_bullet_point(self):
        data = {'text': 'hello', 'plain_text': 'hello'}
        response = self.get_edit_response(
            self.user,
            self.bullet_point.id,
            data
        )
        self.bullet_point.refresh_from_db()
        self.assertTrue(self.bullet_point.is_tail)
        self.assertFalse(self.bullet_point.is_head)
        self.assertEqual(len(self.bullet_point.editors), 1)
        response_json = response.json()
        self.assertContains(response, 'is_tail":false', status_code=201)
        self.assertTrue(response_json['is_head'])
        self.assertEqual(response_json['tail'], self.bullet_point.id)

    def get_delete_response(self, user, bullet_point_id):
        url = self.base_url + str(bullet_point_id) + '/'
        data = None
        return get_authenticated_delete_response(
            user,
            url,
            data,
            content_type='application/json'
        )

    def get_edit_response(self, user, bullet_point_id, data):
        url = self.base_url + str(bullet_point_id) + '/edit/'
        return get_authenticated_post_response(
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
