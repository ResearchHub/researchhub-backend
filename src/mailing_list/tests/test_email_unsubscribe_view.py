from urllib.parse import parse_qs, urlencode, urlsplit

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from mailing_list.models import EmailOptOut
from mailing_list.services import EmailSubscriptionService

EMAIL = "reader@example.com"


class EmailUnsubscribeViewTests(APITestCase):
    def setUp(self):
        self.url = reverse("email_unsubscribe")
        unsubscribe_url = EmailSubscriptionService().generate_unsubscribe_url(EMAIL)
        self.code = parse_qs(urlsplit(unsubscribe_url).query)["code"][0]

    def test_opts_out_from_a_json_body(self):
        # Act
        response = self.client.post(self.url, {"code": self.code}, format="json")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"detail": "Email address unsubscribed."})
        self.assertTrue(EmailOptOut.objects.filter(email=EMAIL).exists())

    def test_one_click_post_reads_the_code_from_the_query_string(self):
        # Arrange
        url = f"{self.url}?{urlencode({'code': self.code})}"

        # Act
        response = self.client.post(
            url,
            "List-Unsubscribe=One-Click",
            content_type="application/x-www-form-urlencoded",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(EmailOptOut.objects.filter(email=EMAIL).exists())

    def test_repeated_unsubscribe_stays_successful(self):
        # Arrange
        EmailOptOut.add(EMAIL)

        # Act
        response = self.client.post(self.url, {"code": self.code}, format="json")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(EmailOptOut.objects.count(), 1)

    def test_rejects_invalid_code(self):
        # Arrange
        invalid_code = "invalid-code"

        # Act
        response = self.client.post(
            self.url,
            {"code": invalid_code},
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(EmailOptOut.objects.count(), 0)

    def test_rejects_a_request_without_a_code(self):
        # Act
        response = self.client.post(self.url, {}, format="json")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(EmailOptOut.objects.count(), 0)
