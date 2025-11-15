from unittest import TestCase

from django.test import override_settings

from paper.tasks import _create_download_url


class TestTasks(TestCase):

    @override_settings(SCRAPER_URL="https://scraper/?url={url}")
    def test_create_download_url(self):
        # Arrange
        test_cases = [
            (
                "https://arxiv.org/pdf/1234.56789.pdf",
                "arxiv",
                "https://scraper/?url=https%3A//arxiv.org/pdf/1234.56789.pdf",
            ),
            (
                "https://www.biorxiv.org/content/10.1101/2023.10.01.123456v1.full.pdf",
                "biorxiv",
                "https://scraper/?url=https%3A//www.biorxiv.org/content/10.1101/2023.10.01.123456v1.full.pdf",
            ),
            (
                "https://www.example.com/paper.pdf",
                "chemrxiv",
                "https://www.example.com/paper.pdf",
            ),
        ]

        for url, source, expected in test_cases:
            with self.subTest(msg=f"Testing URL: {url} with source: {source}"):
                # Act
                result = _create_download_url(url, source)

                # Assert
                self.assertEqual(result, expected)
                self.assertEqual(result, expected)
                self.assertEqual(result, expected)
