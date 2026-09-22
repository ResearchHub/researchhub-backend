from unittest import TestCase
from unittest.mock import Mock, patch

import requests

from utils.aws_metadata import ec2_private_ip


class EC2PrivateIPTests(TestCase):
    @patch.object(requests, "get")
    @patch.object(requests, "put")
    def test_returns_ip_from_metadata_service(self, mock_put, mock_get):
        # Arrange
        mock_put.return_value = Mock(text="token")
        mock_get.return_value = Mock(text="10.0.1.23")

        # Act
        ip = ec2_private_ip()

        # Assert
        self.assertEqual(ip, "10.0.1.23")
        self.assertEqual(
            mock_get.call_args.kwargs["headers"],
            {"X-aws-ec2-metadata-token": "token"},
        )

    @patch.object(requests, "get")
    @patch.object(requests, "put")
    def test_raises_on_error_response(self, mock_put, mock_get):
        # Arrange
        mock_put.return_value = Mock(text="token")
        error = requests.exceptions.HTTPError("401 Unauthorized")
        mock_get.return_value = Mock(raise_for_status=Mock(side_effect=error))

        # Act & Assert
        with self.assertRaises(requests.exceptions.RequestException):
            ec2_private_ip()
