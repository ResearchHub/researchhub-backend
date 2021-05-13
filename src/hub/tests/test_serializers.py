from django.test import TestCase

from .helpers import create_hub, subscribe
from hub.serializers import HubSerializer
from user.tests.helpers import (
    create_random_authenticated_user,
    create_random_default_user
)
from utils.test_helpers import get_authenticated_get_response


class HubSerializersTests(TestCase):

    def setUp(self):
        self.base_url = '/api/hub/'
        self.hub = create_hub(name='Serializer Test Hub')
        self.user = create_random_authenticated_user('hub_user')

    def test_serializer_shows_subscriber_count(self):
        user = create_random_default_user('serializer_user')
        hub = create_hub(name='Serializer Hub')

        hub = subscribe(hub, user)
        serialized = HubSerializer(hub)
        self.assertEqual(serialized.data['subscriber_count'], 1)

        hub = subscribe(hub, self.user)
        serialized = HubSerializer(hub)
        self.assertEqual(serialized.data['subscriber_count'], 2)

    def test_serializer_shows_user_is_subscribed_when_they_are(self):
        user = create_random_authenticated_user('subscribed')
        subscribe(self.hub, user)
        response = self.get_hub_response(user)
        self.assertContains(
            response,
            '"user_is_subscribed":true',
            status_code=200
        )

    def test_serializer_shows_user_is_NOT_subscribed_when_they_are_NOT(self):
        user = create_random_authenticated_user('not_subscribed')
        response = self.get_hub_response(user)
        self.assertContains(
            response,
            '"user_is_subscribed":false',
            status_code=200
        )

    def get_hub_response(self, user):
        url = self.base_url + f'{self.hub.id}/'
        return get_authenticated_get_response(
            user,
            url,
            content_type='application/json'
        )
