import os
from unittest import TestCase
from unittest.mock import Mock, patch

import requests

from utils import aws_metadata
from utils.aws_metadata import ec2_private_ip, ecs_task_private_ip, private_ip

ECS_METADATA_URI = "http://169.254.170.2/v4/0123456789ab-1234567890"


class PrivateIPTests(TestCase):
    @patch.object(aws_metadata, "ec2_private_ip")
    @patch.object(aws_metadata, "ecs_task_private_ip")
    @patch.dict(os.environ, {"ECS_CONTAINER_METADATA_URI_V4": ECS_METADATA_URI})
    def test_uses_ecs_metadata_when_available(self, mock_ecs, mock_ec2):
        # Arrange
        mock_ecs.return_value = "10.0.2.100"

        # Act
        ip = private_ip()

        # Assert
        self.assertEqual(ip, "10.0.2.100")
        mock_ec2.assert_not_called()

    @patch.object(aws_metadata, "ec2_private_ip")
    @patch.object(aws_metadata, "ecs_task_private_ip")
    @patch.dict(os.environ)
    def test_falls_back_to_ec2_metadata(self, mock_ecs, mock_ec2):
        # Arrange
        os.environ.pop("ECS_CONTAINER_METADATA_URI_V4", None)
        mock_ec2.return_value = "10.0.1.23"

        # Act
        ip = private_ip()

        # Assert
        self.assertEqual(ip, "10.0.1.23")
        mock_ecs.assert_not_called()


class ECSTaskPrivateIPTests(TestCase):
    @patch.object(requests, "get")
    @patch.dict(os.environ, {"ECS_CONTAINER_METADATA_URI_V4": ECS_METADATA_URI})
    def test_returns_ip_from_container_metadata(self, mock_get):
        # Arrange
        mock_get.return_value = Mock(
            json=Mock(
                return_value={
                    "Networks": [
                        {"NetworkMode": "awsvpc", "IPv4Addresses": ["10.0.2.100"]}
                    ]
                }
            )
        )

        # Act
        ip = ecs_task_private_ip()

        # Assert
        self.assertEqual(ip, "10.0.2.100")
        self.assertEqual(mock_get.call_args.args[0], ECS_METADATA_URI)

    @patch.object(requests, "get")
    @patch.dict(os.environ, {"ECS_CONTAINER_METADATA_URI_V4": ECS_METADATA_URI})
    def test_raises_on_error_response(self, mock_get):
        # Arrange
        error = requests.exceptions.HTTPError("500 Internal Server Error")
        mock_get.return_value = Mock(raise_for_status=Mock(side_effect=error))

        # Act & Assert
        with self.assertRaises(requests.exceptions.RequestException):
            ecs_task_private_ip()


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
