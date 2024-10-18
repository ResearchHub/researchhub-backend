from django.test import TestCase

from hub.models import Hub
from tag.models import Concept
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

    def test_create_or_update_hub_from_concept(self):
        # Arrange
        concept = Concept.objects.create(
            display_name="testConcept1",
        )

        # Act
        actual = Hub.create_or_update_hub_from_concept(concept)

        # Assert
        expected = Hub.objects.get(concept=concept)
        self.assertIsNotNone(expected)
        self.assertEqual(actual, expected)

    def test_create_or_update_hub_from_concept_when_hub_already_exists(self):
        # Arrange
        hub = Hub.objects.create(
            name="testConcept1",
        )

        concept = Concept.objects.create(
            display_name=hub.name,
        )

        # Act
        actual = Hub.create_or_update_hub_from_concept(concept)

        # Assert
        self.assertEqual(actual, hub)

    def test_create_or_update_hub_from_concept_with_different_cases(self):
        # Arrange
        hub = Hub.objects.create(
            name="testConcept1",
        )

        concept = Concept.objects.create(
            display_name="TESTCONCEPT1",
        )

        # Act
        actual = Hub.create_or_update_hub_from_concept(concept)

        # Assert
        self.assertEqual(actual, hub)

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
