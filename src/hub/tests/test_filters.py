from django.test import TestCase

from hub.filters import HubFilter
from hub.models import Hub


class HubFilterTests(TestCase):

    def test_filter_name__iexact(self):
        # Arrange
        Hub.objects.create(name="hubName1")
        Hub.objects.create(name="hubName2")
        Hub.objects.create(name="hubName3")

        queryset = Hub.objects.all()

        # Act
        filter_instance = HubFilter(
            data={"name__iexact": "hubName2"}, queryset=queryset
        )

        # Assert
        self.assertEqual(len(filter_instance.qs), 1)
        self.assertEqual(filter_instance.qs[0].name, "hubName2")

    def test_filter_name__iexact_with_different_case(self):
        # Arrange
        Hub.objects.create(name="hubName1")
        Hub.objects.create(name="hubName2")
        Hub.objects.create(name="hubName3")

        queryset = Hub.objects.all()

        # Act
        filter_instance = HubFilter(
            data={"name__iexact": "HUBNAME2"}, queryset=queryset
        )

        # Assert
        self.assertEqual(len(filter_instance.qs), 1)
        self.assertEqual(filter_instance.qs[0].name, "hubName2")
