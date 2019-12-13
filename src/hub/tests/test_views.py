from django.test import TestCase

from .helpers import create_hub
from user.tests.helpers import (
    create_random_default_user,
    create_random_authenticated_user
)
from utils.test_helpers import get_authenticated_post_response


class HubViewsTests(TestCase):

    def setUp(self):
        self.base_url = '/api/hub/'
        self.hub = create_hub(name='View Test Hub')
        self.user = create_random_authenticated_user('hub_user')

    def test_can_subscribe_to_hub(self):
        start_state = self.is_subscribed(self.user, self.hub)
        self.assertFalse(start_state)

        self.get_hub_subscribe_response(self.user)

        self.hub.refresh_from_db()
        end_state = self.is_subscribed(self.user, self.hub)
        self.assertTrue(end_state)

    def test_can_unsubscribe_to_hub(self):
        self.hub.subscribers.add(self.user)
        self.hub.save()

        start_state = self.is_subscribed(self.user, self.hub)
        self.assertTrue(start_state)

        self.get_hub_unsubscribe_response(self.user)

        self.hub.refresh_from_db()
        end_state = self.is_subscribed(self.user, self.hub)
        self.assertFalse(end_state)

    def test_hub_unlocks_after_15_subscriptions(self):
        users = self.create_users(14)
        hub = create_hub('Confetti')
        hub.subscribers.add(*users)

        hub.refresh_from_db()
        self.assertTrue(hub.is_locked)

        self.get_hub_subscribe_response(self.user, hub=hub)

        hub.refresh_from_db()
        self.assertFalse(hub.is_locked)

    def is_subscribed(self, user, hub):
        return user in hub.subscribers.all()

    def create_users(self, amount):
        users = []
        for x in range(amount):
            user = create_random_default_user(f'users{x}')
            users.append(user)
        return users

    def get_hub_subscribe_response(self, user, hub=None):
        if hub is None:
            hub = self.hub

        url = self.base_url + f'{hub.id}/subscribe/'
        return self.get_hub_response(url, user)

    def get_hub_unsubscribe_response(self, user):
        url = self.base_url + f'{self.hub.id}/unsubscribe/'
        return self.get_hub_response(url, user)

    def get_hub_response(self, url, user):
        data = None
        return get_authenticated_post_response(
            user,
            url,
            data
        )
