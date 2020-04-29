from django.test import TestCase

from bullet_point.tests.helpers import create_bullet_point
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


class BulletPointPermissionsTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user('BP')
        self.base_url = '/api/bullet_point/'
        self.paper = create_paper()
        self.bullet_point = create_bullet_point(
            paper=self.paper,
            created_by=self.user
        )

    def test_user_can_create_bullet_point_with_at_least_1_rep(self):
        user = create_random_authenticated_user('A')
        data = {
            'paper': self.paper.id,
            'created_by': 2,
            'bullet_type': 'LIMITATION'
        }
        response = self.get_post_response(user, data=data)
        self.assertContains(response, 'id', status_code=201)

    def test_user_can_NOT_create_bullet_point_with_below_1_rep(self):
        user = create_random_authenticated_user_with_reputation('B', 0)
        response = self.get_post_response(user)
        self.assertContains(response, 'permission', status_code=403)

    def test_can_NOT_put(self):
        response = self.get_put_response(self.user, self.bullet_point.id)
        self.assertContains(response, 'permission', status_code=403)

    def test_can_NOT_set_created_by(self):
        user = create_random_authenticated_user('Ba')
        data = {
            'paper': self.paper.id,
            'created_by': 2,
            'bullet_type': 'LIMITATION'
        }

        response = self.get_post_response(user, data=data)
        self.assertContains(response, 'created_by":{', status_code=201)

        response = self.get_patch_response(user, self.bullet_point.id, data)
        self.assertContains(response, 'permission', status_code=400)

    def test_ONLY_moderators_can_update_ordinal_lock(self):
        user = create_random_authenticated_user('C')
        response = self.get_lock_ordinal_response(user, self.bullet_point.id)
        self.assertContains(response, 'permission', status_code=403)

        self.paper.moderators.add(user)
        response = self.get_lock_ordinal_response(user, self.bullet_point.id)
        text = 'ordinal_is_locked":true'
        self.assertContains(response, text, status_code=200)

    def test_ONLY_moderators_can_update_is_removed(self):
        user = create_random_authenticated_user('D')
        response = self.get_remove_response(
            user,
            self.bullet_point.id,
            remove=False
        )
        self.assertContains(response, 'permission', status_code=403)

        self.paper.moderators.add(user)
        response = self.get_remove_response(
            user,
            self.bullet_point.id,
            remove=False
        )
        text = 'is_removed":false'
        self.assertContains(response, text, status_code=200)

    def test_ONLY_staff_can_delete(self):
        bullet_point = create_bullet_point()
        user = create_random_authenticated_user('E')
        staff = create_random_authenticated_user('E_staff')
        staff.is_staff = True
        staff.save()

        response = self.get_delete_response(user, bullet_point.id)
        self.assertContains(response, 'permission', status_code=403)

        response = self.get_delete_response(staff, bullet_point.id)
        self.assertContains(response, '', status_code=204)

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
