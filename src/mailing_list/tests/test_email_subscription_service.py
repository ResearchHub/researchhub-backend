from urllib.parse import parse_qs, urlsplit

from django.core import signing
from django.test import TestCase

from mailing_list.models import EmailOptOut
from mailing_list.services.email_subscription_service import (
    EmailSubscriptionService,
    InvalidUnsubscribeCodeError,
)

EMAIL = "reader@example.com"


def _unsubscribe_code(service: EmailSubscriptionService, email: str = EMAIL) -> str:
    url = service.generate_unsubscribe_url(email)
    return parse_qs(urlsplit(url).query)["code"][0]


class GenerateCodeTests(TestCase):
    def setUp(self):
        self.service = EmailSubscriptionService()

    def test_code_round_trips_a_normalized_email(self):
        # Arrange
        code = _unsubscribe_code(self.service, " Reader@Example.COM ")

        # Act
        self.service.unsubscribe(code)

        # Assert
        self.assertTrue(EmailOptOut.objects.filter(email=EMAIL).exists())

    def test_codes_differ_between_addresses(self):
        # Act
        first = _unsubscribe_code(self.service, EMAIL)
        second = _unsubscribe_code(self.service, "other@example.com")

        # Assert
        self.assertNotEqual(first, second)


class GenerateUrlTests(TestCase):
    def test_url_points_to_the_frontend_and_carries_the_code(self):
        # Arrange
        service = EmailSubscriptionService(
            frontend_url="https://www.example.com/email/unsubscribe/"
        )

        # Act
        url = service.generate_unsubscribe_url(EMAIL)

        # Assert
        parsed_url = urlsplit(url)
        code = parse_qs(parsed_url.query)["code"][0]
        self.assertEqual(
            f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}",
            "https://www.example.com/email/unsubscribe/",
        )
        self.assertTrue(code)
        self.assertNotIn("email=", url)

    def test_preserves_existing_query_parameters(self):
        # Arrange
        service = EmailSubscriptionService(
            frontend_url="https://www.example.com/email/unsubscribe/?source=email"
        )

        # Act
        url = service.generate_unsubscribe_url(EMAIL)

        # Assert
        self.assertEqual(parse_qs(urlsplit(url).query)["source"], ["email"])

    def test_list_unsubscribe_url_points_to_the_frontend_proxy(self):
        # Arrange
        service = EmailSubscriptionService(
            list_unsubscribe_url="https://www.example.com/api/email/unsubscribe"
        )

        # Act
        url = service.generate_list_unsubscribe_url(EMAIL)

        # Assert
        parsed_url = urlsplit(url)
        self.assertEqual(
            f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}",
            "https://www.example.com/api/email/unsubscribe",
        )
        self.assertTrue(parse_qs(parsed_url.query)["code"][0])


class ReadCodeTests(TestCase):
    def setUp(self):
        self.service = EmailSubscriptionService()

    def test_rejects_a_malformed_code(self):
        # Act & Assert
        with self.assertRaises(InvalidUnsubscribeCodeError):
            self.service.unsubscribe("not-a-code")

    def test_rejects_a_signed_payload_without_a_valid_email(self):
        # Arrange
        service = EmailSubscriptionService()
        code = signing.dumps({"email": "not-an-email"})

        # Act & Assert
        with self.assertRaises(InvalidUnsubscribeCodeError):
            service.unsubscribe(code)


class UnsubscribeTests(TestCase):
    def setUp(self):
        self.service = EmailSubscriptionService()
        self.code = _unsubscribe_code(self.service)

    def test_creates_an_email_opt_out(self):
        # Act
        created = self.service.unsubscribe(self.code)

        # Assert
        self.assertTrue(created)
        self.assertTrue(EmailOptOut.objects.filter(email=EMAIL).exists())

    def test_is_idempotent(self):
        # Arrange
        self.service.unsubscribe(self.code)

        # Act
        created = self.service.unsubscribe(self.code)

        # Assert
        self.assertFalse(created)
        self.assertEqual(EmailOptOut.objects.count(), 1)
