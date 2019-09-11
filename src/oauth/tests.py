import json
from django.test import TestCase, Client
from user.models import User
from rest_framework import status
from rest_framework.test import APIClient, APITestCase


class OAuthTests(TestCase):
    invalid_email = 'testuser@gmail'
    invalid_password = 'pass'
    valid_email = 'testuser@gmail.com'
    valid_password = 'ReHub940'

    def setUp(self):
        self.client = Client()

    def test_signup(self):
        raise NotImplementedError

    def test_login(self):
        response = self.login(self.valid_email, self.valid_password)
        self.assertEqual(response.status_code, 200)
        self.assertContainsToken(response)

    def test_social_login(self):
        raise NotImplementedError

   def assertContainsToken(self, response):
        self.assertContains(response, 'key')
        token = response.json()['key']
        self.assertTrue(len(token) > 0)

    def signup(self, username, password):
        url = '/auth/signup/'
        body = { "username": username, "email": username, "password1": password, "password2": password}
        return self.post_response(url, body)

    def login(self, username, password):
        self.signup(username, password)
        url = '/auth/login/'
        body = { "email": username, "password": password }
        return self.post_response(url, body)

    def post_response(self, path, data):
        return self.client.post(path, data=json.dumps(data), content_type='application/json')
