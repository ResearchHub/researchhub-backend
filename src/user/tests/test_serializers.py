from django.test import TestCase

from .helpers import create_user


class UserSerializersTests(TestCase):

    def setUp(self):
        self.user = create_user(first_name='Serializ')
