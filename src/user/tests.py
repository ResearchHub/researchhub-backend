import json

from django.test import TestCase, Client
from django.contrib.auth import authenticate, login
from django.http import HttpRequest

from .models import User


class UserTests(TestCase):
    invalid_email = 'testuser@gmail'
    invalid_password = 'pass'
    valid_email = 'testuser@gmail.com'
    valid_password = 'ReHub940'

    def test_string_representation(self):
        user = self.create_user()
        self.assertEquals(str(user), self.valid_email)

    def create_user(
        self,
        email=valid_email,
        password=valid_password,
    ):
        return User.objects.create(
            email=email,
            password=password,
        )


class AuthTests(TestCase):
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

    def test_signup_with_username(self):
        response = self.valid_signup('test_username')
        self.assertContainsToken(response, 201)

    def test_signup_without_username(self):
        response = self.valid_signup()
        self.assertContainsToken(response, 201)

    def test_signup_with_duplicate_email(self):
        response1 = self.valid_signup()
        response2 = self.valid_signup()
        response_text = 'A user is already registered with this e-mail'
        self.assertContains(response2, response_text, status_code=400)

    def test_signup_with_duplicate_username_and_different_email(self):
        username = 'test_username'
        response1 = self.valid_signup(username)
        response2 = self.signup(username, 'different@gmail.com', self.valid_password)
        response_text = 'A user with that username already exists'
        self.assertContains(response2, response_text, status_code=400)

    def test_signup_with_duplicate_blank_username_and_different_email(self):
        response1 = self.valid_signup()
        response2 = self.signup(None, 'different@gmail.com', self.valid_password)
        self.assertContainsToken(response2, 201)

    def test_valid_login(self):
        response = self.valid_login()
        self.assertContainsToken(response, 200)

    def assertContainsToken(self, response, status_code):
        self.assertContains(response, 'key', status_code=status_code)
        token = response.json()['key']
        self.assertTrue(len(token) > 0)

    def valid_signup(self, username=None):
        return self.signup(username, self.valid_email, self.valid_password)

    def valid_login(self):
        return self.login(self.valid_email, self.valid_password)

    def signup(self, username, email, password):
        url = '/auth/signup/'
        body = { "username": username, "email": email, "password1": password, "password2": password}
        if not username:
            del body['username']
        return self.post_response(url, body)

    def login(self, email, password):
        self.signup(email, email, password)
        url = '/auth/login/'
        body = { "email": email, "password": password }
        return self.post_response(url, body)

    def post_response(self, path, data):
        return self.client.post(path, data=json.dumps(data), content_type='application/json')
