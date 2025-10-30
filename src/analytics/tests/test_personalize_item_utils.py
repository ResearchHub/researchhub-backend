"""
Tests for Personalize item utility functions.
"""

from django.conf import settings
from django.db import connection
from django.test import TestCase, override_settings

from analytics.constants.personalize_constants import MAX_TEXT_LENGTH
from analytics.services.personalize_item_utils import (
    assert_no_queries,
    clean_text_for_csv,
)
from user.tests.helpers import create_random_default_user


class CleanTextForCSVTests(TestCase):
    """Tests for clean_text_for_csv function."""

    def test_clean_text_for_csv_removes_html_tags(self):
        """Should strip all HTML tags from text."""
        # Arrange
        text = "<p>Hello <strong>world</strong>!</p>"

        # Act
        result = clean_text_for_csv(text)

        # Assert
        self.assertEqual(result, "Hello world!")

    def test_clean_text_for_csv_truncates_long_text(self):
        """Should truncate text longer than MAX_TEXT_LENGTH."""
        # Arrange
        text = "x" * (MAX_TEXT_LENGTH + 100)

        # Act
        result = clean_text_for_csv(text)

        # Assert
        self.assertEqual(len(result), MAX_TEXT_LENGTH)
        self.assertEqual(result, "x" * MAX_TEXT_LENGTH)

    def test_clean_text_for_csv_returns_none_for_empty_string(self):
        """Should return None for empty or whitespace-only strings."""
        # Arrange
        text = "   "

        # Act
        result = clean_text_for_csv(text)

        # Assert
        self.assertIsNone(result)

    def test_clean_text_for_csv_handles_none_input(self):
        """Should return None when input is None."""
        # Arrange
        text = None

        # Act
        result = clean_text_for_csv(text)

        # Assert
        self.assertIsNone(result)

    def test_clean_text_for_csv_strips_whitespace(self):
        """Should strip leading and trailing whitespace."""
        # Arrange
        text = "  Hello world  "

        # Act
        result = clean_text_for_csv(text)

        # Assert
        self.assertEqual(result, "Hello world")


@override_settings(DEBUG=True)
class AssertNoQueriesDecoratorTests(TestCase):
    """Tests for assert_no_queries decorator."""

    def test_assert_no_queries_passes_when_no_queries(self):
        """Decorator should pass when decorated function makes no queries."""

        # Arrange
        @assert_no_queries
        def no_query_function():
            return "success"

        # Act
        result = no_query_function()

        # Assert
        self.assertEqual(result, "success")

    def test_assert_no_queries_raises_when_queries_made(self):
        """Decorator should raise AssertionError when queries are made."""

        # Arrange
        @assert_no_queries
        def query_function():
            create_random_default_user("testuser")
            return "should not reach"

        # Act & Assert
        with self.assertRaises(AssertionError) as context:
            query_function()

        self.assertIn("unexpected queries", str(context.exception))

    @override_settings(DEBUG=False)
    def test_assert_no_queries_only_active_in_debug_mode(self):
        """Decorator should be no-op when DEBUG=False."""

        # Arrange
        @assert_no_queries
        def query_function():
            create_random_default_user("testuser")
            return "success"

        # Act
        result = query_function()

        # Assert
        self.assertEqual(result, "success")
