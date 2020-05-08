from django.test import TestCase

from django.core.cache import cache
from discussion.tests.helpers import create_thread
from hub.tests.helpers import create_hub
from paper.tests.helpers import create_paper
from user.tests.helpers import (
    create_random_default_user,
    create_random_authenticated_user,
    create_actions
)
from utils.test_helpers import (
    get_authenticated_post_response,
    get_get_response
)


class HubViewsTests(TestCase):

    def setUp(self):
        self.base_url = '/api/hub/'
        self.hub = create_hub(name='View Test Hub')
        self.hub2 = create_hub(name='View Test Hub 2')
        self.user = create_random_authenticated_user('hub_user')

    def test_hub_order_by_score(self):
        hub = create_hub('High Score Hub')
        hub2 = create_hub('Low Score Hub')

        actions = create_actions(10, hub=hub)
        actions = create_actions(5, hub=hub2)

        url = self.base_url + '?ordering=-score'
        response = get_get_response(url)
        response_data = response.data['results']

        h1_first = False
        h2_second = False
        for h in response_data:
            if h['id'] == hub.id:
                h1_first = True
            elif h1_first and h['id'] == hub2.id:
                h2_second = True

        self.assertTrue(h1_first and h2_second)
        cache.clear()
        url = self.base_url + '?ordering=score'
        response = get_get_response(url)
        response_data = response.data['results']

        h2_first = False
        h1_second = False
        for h in response_data:
            if h['id'] == hub2.id:
                h2_first = True
            elif h2_first and h['id'] == hub.id:
                h1_second = True

        self.assertTrue(h2_first and h1_second)

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

        for x in range(11):
            create_thread(paper=paper, created_by=self.user)
        page = 1
        url = self.base_url + f'{hub.id}/latest_actions/?page={page}'
        response = get_get_response(url)
        self.assertContains(response, 'count":11', status_code=200)
        result_count = len(response.data['results'])
        self.assertEqual(result_count, 10)

        page = 2
        url = self.base_url + f'{hub.id}/latest_actions/?page={page}'
        response = get_get_response(url)
        self.assertContains(response, 'count":11', status_code=200)
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
