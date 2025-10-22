"""
Unit tests for headline normalization in search documents.
Tests the critical data transformation logic that handles both string and object
headline formats.
"""

from unittest.mock import Mock

from django.test import TestCase

from search.documents.person import PersonDocument
from search.documents.user import UserDocument


class TestHeadlineNormalization(TestCase):
    """Test headline normalization in UserDocument and PersonDocument."""

    def test_user_document_string_headline(self):
        """Test UserDocument handles string headlines correctly."""
        # Mock user with string headline
        mock_author = Mock()
        mock_author.id = 123
        mock_author.headline = "Software Engineer at TechCorp"
        mock_author.profile_image_indexing = "https://example.com/image.jpg"

        mock_user = Mock()
        mock_user.id = 456
        mock_user.author_profile = mock_author

        user_doc = UserDocument()
        result = user_doc.prepare_author_profile(mock_user)

        self.assertIsNotNone(result)
        self.assertEqual(result["id"], 123)
        self.assertEqual(result["headline"], "Software Engineer at TechCorp")
        self.assertEqual(result["profile_image"], "https://example.com/image.jpg")

    def test_user_document_object_headline(self):
        """Test UserDocument handles object headlines correctly."""
        # Mock user with object headline
        mock_author = Mock()
        mock_author.id = 123
        mock_author.headline = {
            "title": "Software Engineer at TechCorp",
            "isPublic": True,
        }
        mock_author.profile_image_indexing = "https://example.com/image.jpg"

        mock_user = Mock()
        mock_user.id = 456
        mock_user.author_profile = mock_author

        user_doc = UserDocument()
        result = user_doc.prepare_author_profile(mock_user)

        self.assertIsNotNone(result)
        self.assertEqual(result["id"], 123)
        # Should extract title
        self.assertEqual(result["headline"], "Software Engineer at TechCorp")
        self.assertEqual(result["profile_image"], "https://example.com/image.jpg")

    def test_user_document_null_headline(self):
        """Test UserDocument handles null headlines correctly."""
        # Mock user with null headline
        mock_author = Mock()
        mock_author.id = 123
        mock_author.headline = None
        mock_author.profile_image_indexing = ""

        mock_user = Mock()
        mock_user.id = 456
        mock_user.author_profile = mock_author

        user_doc = UserDocument()
        result = user_doc.prepare_author_profile(mock_user)

        self.assertIsNotNone(result)
        self.assertEqual(result["id"], 123)
        # Should be empty string
        self.assertEqual(result["headline"], "")
        self.assertEqual(result["profile_image"], "")

    def test_person_document_string_headline(self):
        """Test PersonDocument handles string headlines correctly."""
        # Mock author with string headline
        mock_author = Mock()
        mock_author.headline = "Software Engineer at TechCorp"

        person_doc = PersonDocument()
        result = person_doc.prepare_headline(mock_author)

        self.assertEqual(result, {"title": "Software Engineer at TechCorp"})

    def test_person_document_object_headline(self):
        """Test PersonDocument handles object headlines correctly."""
        # Mock author with object headline
        mock_author = Mock()
        mock_author.headline = {
            "title": "Software Engineer at TechCorp",
            "isPublic": True,
        }

        person_doc = PersonDocument()
        result = person_doc.prepare_headline(mock_author)

        expected = {"title": "Software Engineer at TechCorp", "isPublic": True}
        self.assertEqual(result, expected)

    def test_person_document_null_headline(self):
        """Test PersonDocument handles null headlines correctly."""
        # Mock author with null headline
        mock_author = Mock()
        mock_author.headline = None

        person_doc = PersonDocument()
        result = person_doc.prepare_headline(mock_author)

        self.assertEqual(result, {"title": ""})

    def test_user_document_missing_title_in_object(self):
        """Test UserDocument handles object headlines with missing title field."""
        # Mock user with object headline missing title
        mock_author = Mock()
        mock_author.id = 123
        # Missing title field
        mock_author.headline = {"isPublic": True}
        mock_author.profile_image_indexing = ""

        mock_user = Mock()
        mock_user.id = 456
        mock_user.author_profile = mock_author

        user_doc = UserDocument()
        result = user_doc.prepare_author_profile(mock_user)

        self.assertIsNotNone(result)
        # Should default to empty string
        self.assertEqual(result["headline"], "")

    def test_person_document_missing_title_in_object(self):
        """Test PersonDocument handles object headlines with missing title field."""
        # Mock author with object headline missing title
        mock_author = Mock()
        # Missing title field
        mock_author.headline = {"isPublic": True}

        person_doc = PersonDocument()
        result = person_doc.prepare_headline(mock_author)

        # Should preserve the original object but add empty title
        expected = {"isPublic": True, "title": ""}
        self.assertEqual(result, expected)

    def test_user_document_author_profile_missing(self):
        """Test UserDocument handles missing author profile gracefully."""
        # Mock user without author profile
        mock_user = Mock()
        mock_user.id = 456
        mock_user.author_profile = None

        user_doc = UserDocument()
        result = user_doc.prepare_author_profile(mock_user)

        self.assertIsNone(result)
