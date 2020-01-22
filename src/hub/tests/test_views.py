from django.test import TestCase

from discussion.tests.helpers import create_thread
from hub.tests.helpers import create_hub
from paper.tests.helpers import create_paper
from user.tests.helpers import (
    create_random_default_user,
    create_random_authenticated_user
)
from utils.test_helpers import (
    get_authenticated_post_response,
    get_get_response
)


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

    def test_invite_to_hub(self):
        hub = create_hub('Invite to Hub')
        email = 'val@quantfive.org'

        response = self.get_invite_to_hub_response(
            self.user,
            hub,
            [email]
        )
        self.assertContains(response, email, status_code=200)

    def test_invite_to_hub_does_not_email_subscribers(self):
        subscriber = create_random_default_user('subscriber')
        subscriber.email = 'val@quantfive.org'  # Must use whitelisted email
        subscriber.save()
        hub = create_hub('Invite to Hub No Email')
        hub.subscribers.add(subscriber)

        response = self.get_invite_to_hub_response(
            self.user,
            hub,
            [subscriber.email]
        )
        self.assertNotContains(response, subscriber.email, status_code=200)

    def test_hub_actions_is_paginated(self):
        hub = create_hub(name='Calpurnia')
        paper = create_paper()
        hub.papers.add(paper)

        for x in range(21):
            create_thread(paper=paper, created_by=self.user)
        page = 1
        url = self.base_url + f'latest_hub_actions/?hub={hub.id}&page={page}'
        response = get_get_response(url)
        self.assertContains(response, 'count":21', status_code=200)
        result_count = len(response.data['results'])
        self.assertEqual(result_count, 20)

        page = 2
        url = self.base_url + f'latest_hub_actions/?hub={hub.id}&page={page}'
        response = get_get_response(url)
        self.assertContains(response, 'count":21', status_code=200)
        result_count = len(response.data['results'])
        self.assertEqual(result_count, 1)

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

    def get_invite_to_hub_response(self, user, hub, emails):
        url = self.base_url + f'{hub.id}/invite_to_hub/'
        data = {
            'emails': emails
        }
        return get_authenticated_post_response(
            user,
            url,
            data,
            headers={'HTTP_ORIGIN': 'researchhub.com'}
        )
