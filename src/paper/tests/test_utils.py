from unittest import TestCase

from paper.utils import _ngrams


class UtilsTest(TestCase):
    def test_ngrams(self):
        # Arrange
        given = "This is a sample text for testing ngrams"

        expected = [
            ("This", "is"),
            ("is", "a"),
            ("a", "sample"),
            ("sample", "text"),
            ("text", "for"),
            ("for", "testing"),
            ("testing", "ngrams"),
        ]

        # Act
        actual = list(_ngrams(given.split(), 2))

        # Assert
        self.assertEqual(len(actual), 7)
        self.assertEqual(actual, expected)
