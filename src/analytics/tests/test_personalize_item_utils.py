"""
Tests for Personalize item utility functions.
"""

from django.test import TestCase

from analytics.constants.personalize_constants import MAX_TEXT_LENGTH
from analytics.utils.personalize_item_utils import prepare_text_for_personalize


class CleanTextForCSVTests(TestCase):
    """Tests for prepare_text_for_personalize function."""

    def test_prepare_text_for_personalize_removes_html_tags(self):
        """Should strip all HTML tags from text."""
        # Arrange
        text = "<p>Hello <strong>world</strong>!</p>"

        # Act
        result = prepare_text_for_personalize(text)

        # Assert
        self.assertEqual(result, "Hello world!")

    def test_prepare_text_for_personalize_truncates_long_text(self):
        """Should truncate text longer than MAX_TEXT_LENGTH."""
        # Arrange
        text = "x" * (MAX_TEXT_LENGTH + 100)

        # Act
        result = prepare_text_for_personalize(text)

        # Assert
        self.assertEqual(len(result), MAX_TEXT_LENGTH)
        self.assertEqual(result, "x" * MAX_TEXT_LENGTH)

    def test_prepare_text_for_personalize_returns_none_for_empty_string(self):
        """Should return None for empty or whitespace-only strings."""
        # Arrange
        text = "   "

        # Act
        result = prepare_text_for_personalize(text)

        # Assert
        self.assertIsNone(result)

    def test_prepare_text_for_personalize_handles_none_input(self):
        """Should return None when input is None."""
        # Arrange
        text = None

        # Act
        result = prepare_text_for_personalize(text)

        # Assert
        self.assertIsNone(result)

    def test_prepare_text_for_personalize_strips_whitespace(self):
        """Should strip leading and trailing whitespace."""
        # Arrange
        text = "  Hello world  "

        # Act
        result = prepare_text_for_personalize(text)

        # Assert
        self.assertEqual(result, "Hello world")
