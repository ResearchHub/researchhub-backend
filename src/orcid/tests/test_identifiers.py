from django.test import SimpleTestCase

from orcid.identifiers import normalize_orcid


class NormalizeOrcidTests(SimpleTestCase):
    def test_normalizes_supported_formats_to_consistent_output(self):
        # Arrange
        cases = [
            (
                "https://orcid.org/0000-0001-2345-6789",
                "https://orcid.org/0000-0001-2345-6789",
                "0000-0001-2345-6789",
            ),
            (
                "http://www.orcid.org/0000-0001-2345-6789/",
                "https://orcid.org/0000-0001-2345-6789",
                "0000-0001-2345-6789",
            ),
            (
                "0000-0001-2345-6789",
                "https://orcid.org/0000-0001-2345-6789",
                "0000-0001-2345-6789",
            ),
            (None, None, None),
            ("", None, None),
        ]

        # Act & Assert
        for input_value, expected_url, expected_bare in cases:
            with self.subTest(input_value=input_value):
                url, bare = normalize_orcid(input_value)
                self.assertEqual(url, expected_url)
                self.assertEqual(bare, expected_bare)
