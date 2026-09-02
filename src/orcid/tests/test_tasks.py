from unittest.mock import Mock, patch

from django.test import TestCase

from orcid.tasks import sync_orcid_task


class SyncOrcidTaskTests(TestCase):
    @patch("orcid.tasks.OrcidFetchService")
    def test_calls_service(self, mock_service_class: Mock) -> None:
        """The task delegates ORCID synchronization to the service."""
        # Arrange
        mock_service = Mock()
        mock_service_class.return_value = mock_service

        # Act
        sync_orcid_task(1)

        # Assert
        mock_service.sync_orcid.assert_called_once_with(1)

    @patch("orcid.tasks.OrcidFetchService")
    def test_raises_on_error(self, mock_service_class: Mock) -> None:
        """The task propagates ORCID synchronization errors."""
        # Arrange
        mock_service = Mock()
        mock_service.sync_orcid.side_effect = ValueError("No ORCID")
        mock_service_class.return_value = mock_service

        # Act & Assert
        with self.assertRaises(ValueError):
            sync_orcid_task(1)
