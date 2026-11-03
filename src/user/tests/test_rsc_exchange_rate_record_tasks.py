from unittest import mock

import requests
from django.test import TestCase

from purchase.models import RscExchangeRate
from user.rsc_exchange_rate_record_tasks import (
    RSC_COIN_GECKO_ID,
    rsc_exchange_rate_record_tasks,
)
from user.tasks import execute_rsc_exchange_rate_record_tasks


def _gecko_response(rate=0.5, status_code=200):
    response = mock.Mock()
    response.status_code = status_code
    response.json.return_value = {RSC_COIN_GECKO_ID: {"usd": rate}}
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
    return response


class RscExchangeRateRecordTasksTests(TestCase):
    @mock.patch("user.rsc_exchange_rate_record_tasks.requests.get")
    def test_records_rate(self, mock_get):
        # Arrange
        mock_get.return_value = _gecko_response(rate=0.42)

        # Act
        result = rsc_exchange_rate_record_tasks()

        # Assert
        self.assertEqual(result["rate"], 0.42)
        self.assertEqual(RscExchangeRate.objects.get().rate, 0.42)

    @mock.patch("user.rsc_exchange_rate_record_tasks.requests.get")
    def test_timeout_is_raised_for_retry(self, mock_get):
        # Arrange
        mock_get.side_effect = requests.exceptions.ReadTimeout()

        # Act & Assert
        with self.assertRaises(requests.exceptions.ReadTimeout):
            rsc_exchange_rate_record_tasks()
        self.assertFalse(RscExchangeRate.objects.exists())

    @mock.patch("user.rsc_exchange_rate_record_tasks.requests.get")
    def test_http_error_is_raised_for_retry(self, mock_get):
        # Arrange
        mock_get.return_value = _gecko_response(status_code=429)

        # Act & Assert
        with self.assertRaises(requests.HTTPError):
            rsc_exchange_rate_record_tasks()

    @mock.patch("user.rsc_exchange_rate_record_tasks.requests.get")
    def test_task_records_rate_after_transient_timeout(self, mock_get):
        # Arrange
        mock_get.side_effect = [
            requests.exceptions.ReadTimeout(),
            _gecko_response(rate=0.37),
        ]

        # Act
        # Eager apply runs autoretry inline (CELERY_TASK_ALWAYS_EAGER in tests).
        execute_rsc_exchange_rate_record_tasks.apply()

        # Assert
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(RscExchangeRate.objects.get().rate, 0.37)
