import json
from django.test import TestCase, Client
from user.models import User


class OAuthTests(TestCase):
    """
    Status code reference:
        https://www.iana.org/assignments/http-status-codes/http-status-codes.xhtml
    """
    invalid_email = 'testuser@gmail'
    invalid_password = 'pass'
    valid_email = 'testuser@gmail.com'
    valid_password = 'ReHub940'

    def setUp(self):
        self.client = Client()

    def test_valid_signup(self):
        response = self.valid_signup()
        self.assertContainsToken(response, 201)

    def test_valid_login(self):
        response = self.valid_login()
        self.assertContainsToken(response, 200)

    def test_social_login(self):
        # TODO: Implement this

    def assertContainsToken(self, response, status_code):
        self.assertContains(response, 'key', status_code=status_code)
        token = response.json()['key']
        self.assertTrue(len(token) > 0)

    def valid_signup(self):
        return self.signup(self.valid_email, self.valid_password)

    def valid_login(self):
        return self.login(self.valid_email, self.valid_password)

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
