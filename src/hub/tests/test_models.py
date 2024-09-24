from django.test import TestCase

from hub.models import Hub


class HubModelsTests(TestCase):

    def test_hub_str(self):
        # Arrange
        hub = Hub.objects.create(
            name="Test Hub 1",
            namespace=Hub.Namespace.JOURNAL,
        )

        # Act
        actual = str(hub)

        # Assert
        self.assertEqual(actual, "journal:test hub 1, locked: False")
