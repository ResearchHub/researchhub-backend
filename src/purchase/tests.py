from django.test import TestCase

from psycopg2.errors import UniqueViolation

from django.db import IntegrityError
from django.test import TestCase, TransactionTestCase, tag, Client
from user.tests.helpers import (
    create_random_default_user,
    create_moderator,
)
from rest_framework.test import APITestCase
from utils.test_helpers import (
    IntegrationTestHelper,
    TestHelper,
)

# Create your tests here.
class SendRSCTest(
    APITestCase,
    TestCase,
    TestHelper,
    IntegrationTestHelper
):
    base_url = '/api/transactions/send_rsc/'
    balance_amount = 50

    def setUp(self):
      self.recipient = create_random_default_user('recipient')

    def test_regular_user_send_rsc(self):
        client = self.get_default_authenticated_client()
        response = self.send_rsc(client, self.recipient)
        self.assertEqual(response.status_code, 403)
    
    def test_moderator_user_send_rsc(self):
        moderator = create_moderator(first_name='moderator', last_name='moderator')
        self.client.force_authenticate(moderator)
        response = self.send_rsc(self.client, self.recipient)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.recipient.balances.count(), 1)
        self.assertEqual(int(self.recipient.balances.first().amount), self.balance_amount)
        

    def test_unauthenticated_user_send_rsc(self):
        response = self.send_rsc(self.client, self.recipient)
        self.assertEqual(response.status_code, 401)

    def send_rsc(self, client, user):
        url = self.base_url
        form_data = self.build_form(user)
        response = client.post(url, form_data)
        return response

    def build_form(self, user):
        form = {
            'recipient_id': user.id,
            'amount': self.balance_amount
        }
        return form
