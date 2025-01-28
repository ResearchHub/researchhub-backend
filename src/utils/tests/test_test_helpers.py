import string

from django.test import TestCase

from utils.test_helpers import generate_password


class TestTestHelpers(TestCase):
    def test_generate_password(self):
        password = generate_password()
        self.assertEqual(len(password), 16)
        self.assertTrue(any(c.isalpha() for c in password))
        self.assertTrue(any(c.isdigit() for c in password))
        self.assertTrue(any(c in string.punctuation for c in password))

    def test_generate_password_with_custom_length(self):
        password = generate_password(length=3)
        self.assertEqual(len(password), 3)
        self.assertTrue(any(c.isalpha() for c in password))
        self.assertTrue(any(c.isdigit() for c in password))
        self.assertTrue(any(c in string.punctuation for c in password))
