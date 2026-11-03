import unittest

from hub.models import Hub
from search.documents.hub import HubDocument


class HubDocumentShouldIndexTests(unittest.TestCase):
    def setUp(self):
        self.document = HubDocument()

    def test_should_index_object_includes_active_hub(self):
        # Arrange
        hub = Hub(name="Biology", namespace=Hub.Namespace.CATEGORY)

        # Act
        result = self.document.should_index_object(hub)

        # Assert
        self.assertTrue(result)

    def test_should_index_object_excludes_removed_hub(self):
        # Arrange
        hub = Hub(name="Biology", namespace=Hub.Namespace.CATEGORY, is_removed=True)

        # Act
        result = self.document.should_index_object(hub)

        # Assert
        self.assertFalse(result)

    def test_should_index_object_excludes_journal(self):
        # Arrange
        hub = Hub(name="Nature", namespace=Hub.Namespace.JOURNAL)

        # Act
        result = self.document.should_index_object(hub)

        # Assert
        self.assertFalse(result)
