from unittest.mock import Mock

from django.test import TestCase
from opensearchpy import Document
from rest_framework import serializers

from search.base.serializers import ElasticsearchListSerializer, ElasticsearchSerializer


def create_mock_document(**kwargs):
    doc = Mock(spec=Document)
    doc.to_dict.return_value = kwargs.copy()

    # Allow attribute access for fields (needed for SerializerMethodField)
    for key, value in kwargs.items():
        setattr(doc, key, value)

    return doc


class TestElasticsearchSerializer(TestCase):
    def setUp(self):
        self.serializer = ElasticsearchSerializer()

    def test_to_representation_basic_document(self):
        """Test serializing a basic document with simple fields"""
        # Arrange
        doc = create_mock_document(id=1, name="Test", description="A test document")

        # Act
        result = self.serializer.to_representation(doc)

        # Assert
        self.assertEqual(result["id"], 1)
        self.assertEqual(result["name"], "Test")
        self.assertEqual(result["description"], "A test document")

    def test_to_representation_raises_error_for_non_document(self):
        """Test that TypeError is raised for non-Document instances"""
        # Arrange
        regular_dict = {"id": 1, "name": "Test"}

        # Act
        with self.assertRaises(TypeError) as context:
            self.serializer.to_representation(regular_dict)

        # Assert
        self.assertIn(
            "Expected an instance of opensearchpy.Document", str(context.exception)
        )

    def test_to_representation_includes_meta_fields(self):
        """Test that document meta.highlight is included"""
        # Arrange
        doc = create_mock_document(name="Test")
        doc.meta = Mock()
        doc.meta.score = 42.5
        doc.meta.id = "doc_12345"

        highlight_mock = Mock()
        highlight_mock.to_dict.return_value = {
            "title": ["<em>Test</em> document"],
            "content": ["This is a <em>test</em>"],
        }
        doc.meta.highlight = highlight_mock

        # Act
        result = self.serializer.to_representation(doc)

        # Assert
        self.assertEqual(result["_score"], 42.5)
        self.assertEqual(result["id"], "doc_12345")
        self.assertEqual(
            result["highlight"],
            {
                "title": ["<em>Test</em> document"],
                "content": ["This is a <em>test</em>"],
            },
        )

    def test_to_representation_handles_missing_meta_attributes(self):
        """Test that missing meta attributes don't cause errors"""
        # Arrange
        doc = create_mock_document(name="Test")
        doc.meta = Mock(spec=[])

        # Act
        result = self.serializer.to_representation(doc)

        # Assert
        self.assertEqual(result["name"], "Test")
        self.assertNotIn("_score", result)

    def test_to_representation_with_meta_fields_filtering(self):
        """Test that Meta.fields filters the output correctly"""

        # Arrange
        class FilteredSerializer(ElasticsearchSerializer):
            class Meta:
                fields = ["id", "name"]

        serializer = FilteredSerializer()
        doc = create_mock_document(
            id=1, name="Test", description="Should be filtered out"
        )

        # Act
        result = serializer.to_representation(doc)

        # Assert
        self.assertEqual(result["id"], 1)
        self.assertEqual(result["name"], "Test")
        self.assertNotIn("description", result)

    def test_to_representation_with_serializer_method_field(self):
        """Test that SerializerMethodField works correctly"""

        # Arrange
        class CustomSerializer(ElasticsearchSerializer):
            custom_field = serializers.SerializerMethodField()

            class Meta:
                fields = ["id", "name", "custom_field"]

            def get_custom_field(self, obj):
                return f"Custom: {obj.name}"

        serializer = CustomSerializer()
        doc = create_mock_document(id=1, name="Test")

        # Act
        result = serializer.to_representation(doc)

        # Assert
        self.assertEqual(result["id"], 1)
        self.assertEqual(result["name"], "Test")
        self.assertEqual(result["custom_field"], "Custom: Test")

    def test_to_representation_serializer_method_field_not_in_allowed_fields(self):
        """Test that SerializerMethodField is skipped if not in Meta.fields"""

        # Arrange
        class CustomSerializer(ElasticsearchSerializer):
            custom_field = serializers.SerializerMethodField()

            class Meta:
                fields = ["id", "name"]  # custom_field not included

            def get_custom_field(self, obj):
                return "Should not appear"

        serializer = CustomSerializer()
        doc = create_mock_document(id=1, name="Test")

        # Act
        result = serializer.to_representation(doc)

        # Assert
        self.assertNotIn("custom_field", result)

    def test_to_representation_handles_field_attribute_error(self):
        """Test that AttributeError in field processing is handled gracefully"""

        # Arrange
        class CustomSerializer(ElasticsearchSerializer):
            problematic_field = serializers.SerializerMethodField()

            class Meta:
                fields = ["id", "name", "problematic_field"]

            def get_problematic_field(self, obj):
                return obj.nonexistent_attr

        serializer = CustomSerializer()
        doc = create_mock_document(id=1, name="Test")

        # Act
        result = serializer.to_representation(doc)

        # Assert
        self.assertEqual(result["id"], 1)
        self.assertEqual(result["name"], "Test")
        self.assertNotIn("problematic_field", result)

    def test_to_representation_field_with_none_value(self):
        """Test that fields with None values are included as None"""

        # Arrange
        class CustomSerializer(ElasticsearchSerializer):
            nullable_field = serializers.SerializerMethodField()

            class Meta:
                fields = ["id", "nullable_field"]

            def get_nullable_field(self, obj):
                return None

        serializer = CustomSerializer()
        doc = create_mock_document(id=1, name="Test")

        # Act
        result = serializer.to_representation(doc)

        # Assert
        self.assertEqual(result["nullable_field"], None)

    def test_to_representation_with_nested_data(self):
        """Test serializing documents with nested data structures"""
        # Arrange
        doc = create_mock_document(
            id=1,
            name="Test",
            metadata={"key1": "value1", "key2": "value2"},
            tags=["tag1", "tag2", "tag3"],
        )

        # Act
        result = self.serializer.to_representation(doc)

        # Assert
        self.assertEqual(result["id"], 1)
        self.assertEqual(result["metadata"], {"key1": "value1", "key2": "value2"})
        self.assertEqual(result["tags"], ["tag1", "tag2", "tag3"])
