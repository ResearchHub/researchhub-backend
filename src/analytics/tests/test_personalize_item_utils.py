"""
Tests for Personalize item utility functions.
"""

from django.test import TestCase

from analytics.constants.personalize_constants import MAX_TEXT_LENGTH
from analytics.utils.personalize_item_utils import clean_text_for_csv


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
