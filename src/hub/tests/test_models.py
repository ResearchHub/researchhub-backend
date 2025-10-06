from django.db import IntegrityError, transaction
from django.test import TestCase

from hub.models import Hub
from topic.models import Subfield


class HubModelsTests(TestCase):

    def test_hub_str(self):
        # Arrange
        hub = Hub.objects.create(
            name="testHub1",
            namespace=Hub.Namespace.JOURNAL,
        )

        # Act
        actual = str(hub)

        # Assert
        self.assertEqual(actual, "journal:testHub1, locked: False")

    def test_get_from_subfield(self):
        # Arrange
        subfield = Subfield.objects.create(
            display_name="testSubfield1",
        )

        expected = Hub.objects.create(
            name=subfield.display_name,
            subfield=subfield,
        )

        # Act
        actual = Hub.get_from_subfield(subfield)

        # Assert
        self.assertEqual(actual, expected)

    def test_get_from_subfield_with_different_cases(self):
        # Arrange
        subfield = Subfield.objects.create(
            display_name="testSubfield1",
        )

        expected = Hub.objects.create(
            name="TESTSUBFIELD1",
            subfield=subfield,
        )

        # Act & Assert
        actual = Hub.get_from_subfield(subfield)

        # Assert
        self.assertEqual(actual, expected)

    def test_get_from_subfield_not_found(self):
        # Arrange
        subfield = Subfield.objects.create(
            display_name="testSubfield1",
        )

        # Act & Assert
        with self.assertRaises(Hub.DoesNotExist):
            Hub.get_from_subfield(subfield)

    def test_slugify_new_hub(self):
        # Arrange
        hub = Hub(name="Test Hub")

        # Act
        hub.save()

        # Assert
        self.assertEqual(hub.slug, "test-hub")
        self.assertIsNone(hub.slug_index)

    def test_slugify_existing_slug(self):
        # Arrange
        Hub.objects.create(name="Test Hub", slug="test-hub")
        new_hub = Hub(name="Test Hub")

        # Act
        new_hub.save()

        # Assert
        self.assertEqual(new_hub.slug, "test-hub-1")
        self.assertEqual(new_hub.slug_index, 1)

    def test_slugify_multiple_existing_slugs(self):
        # Arrange
        Hub.objects.create(name="Test Hub", slug="test-hub")
        Hub.objects.create(name="Test Hub", slug="test-hub-1", slug_index=1)
        Hub.objects.create(name="Test Hub", slug="test-hub-9", slug_index=9)
        Hub.objects.create(name="Test Hub", slug="test-hub-88", slug_index=88)
        new_hub = Hub(name="Test Hub")

        # Act
        new_hub.save()

        # Assert
        self.assertEqual(new_hub.slug, "test-hub-89")
        self.assertEqual(new_hub.slug_index, 89)

    def test_slugify_with_special_characters(self):
        # Arrange
        hub = Hub(name="Test Hub! @#$%^&*()")

        # Act
        hub.save()

        # Assert
        self.assertEqual(hub.slug, "test-hub")
        self.assertIsNone(hub.slug_index)

    def test_slugify_existing_slug_starts_with(self):
        # Arrange
        Hub.objects.create(name="Test Hub Starts With", slug="test-hub-starts-with")
        new_hub = Hub(name="Test Hub")

        # Act
        new_hub.save()

        # Assert
        self.assertEqual(new_hub.slug, "test-hub")
        self.assertIsNone(new_hub.slug_index)

    def test_can_create_hub_if_name_does_not_exist(self):
        """Test that a hub can be created when the name doesn't already exist"""
        # Arrange & Act
        hub = Hub.objects.create(
            name="Unique Hub Name",
            namespace=Hub.Namespace.JOURNAL,
        )

        # Assert
        self.assertIsNotNone(hub)
        self.assertEqual(hub.name, "Unique Hub Name")
        self.assertEqual(Hub.objects.filter(name__iexact="Unique Hub Name").count(), 1)

    def test_cannot_create_duplicate_hub_with_identical_name(self):
        """
        Test that creating a hub with identical name and namespace
        raises IntegrityError
        """
        # Arrange
        Hub.objects.create(
            name="Nature Medicine",
            namespace=Hub.Namespace.JOURNAL,
        )

        # Act & Assert
        with self.assertRaises(IntegrityError):
            Hub.objects.create(
                name="Nature Medicine",
                namespace=Hub.Namespace.JOURNAL,
            )

    def test_cannot_create_duplicate_hub_when_case_is_different(self):
        """
        Test that creating a hub with different case but same name
        raises IntegrityError
        """
        # Arrange
        Hub.objects.create(
            name="Nature Medicine",
            namespace=Hub.Namespace.JOURNAL,
        )

        # Act & Assert - Test lowercase version
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Hub.objects.create(
                    name="nature medicine",
                    namespace=Hub.Namespace.JOURNAL,
                )

        # Act & Assert - Test uppercase version
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Hub.objects.create(
                    name="NATURE MEDICINE",
                    namespace=Hub.Namespace.JOURNAL,
                )

        # Act & Assert - Test mixed case version
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Hub.objects.create(
                    name="NaTuRe MeDiCiNe",
                    namespace=Hub.Namespace.JOURNAL,
                )

    def test_can_create_same_name_with_different_namespace(self):
        """Test that same name can exist with different namespaces"""
        # Arrange
        hub1 = Hub.objects.create(
            name="Medicine",
            namespace=Hub.Namespace.JOURNAL,
        )

        # Act - Create hub with same name but different namespace
        hub2 = Hub.objects.create(
            name="Medicine",
            namespace=None,
        )

        # Assert
        self.assertIsNotNone(hub1)
        self.assertIsNotNone(hub2)
        self.assertNotEqual(hub1.id, hub2.id)
        self.assertEqual(Hub.objects.filter(name__iexact="Medicine").count(), 2)
