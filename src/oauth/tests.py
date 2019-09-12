from django.test import TestCase, Client


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

    def test_social_login(self):
        # TODO: Implement this
        pass
