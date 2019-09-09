from django.test import TestCase
from django.contrib.auth import authenticate, login
from django.http import HttpRequest

from .models import User

class UserTests(TestCase):
    invalid_email = 'testuser@email'
    invalid_password = 'pass'
    valid_email = 'testuser@email.com'
    valid_password = 'ReHub940'

    def create_user(
        self,
        email=valid_email,
        password=valid_password,
    ):
        return User.objects.create(
            email=email,
            password=password,
        )

    def test_string_representation(self):
        user = self.create_user()
        self.assertEquals(str(user), self.valid_email)
