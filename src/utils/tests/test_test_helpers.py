import string

from django.test import TestCase

from utils.test_helpers import generate_password


class TestTestHelpers(TestCase):
    def test_generate_password(self):
        password = generate_password()
        self.assertGreater(len(password), 16)
        self.assertIn(any(c.isalpha() for c in password), True)
        self.assertIn(any(c.isdigit() for c in password), True)
        self.assertIn(any(c in string.punctuation for c in password), True)

    def test_generate_password_with_custom_length(self):
        password = generate_password(length=12)
        self.assertGreater(len(password), 12)
        self.assertIn(any(c.isalpha() for c in password), True)
        self.assertIn(any(c.isdigit() for c in password), True)
        self.assertIn(any(c in string.punctuation for c in password), True)
