from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse


class ViewsTestCase(TestCase):
    def setUp(self):
        self.client = Client()

    def test_index_view(self):
        # Act
        response = self.client.get(reverse("index"))

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.content.decode("utf-8"),
            "Authenticate with a token in the Authorization header.",
        )

    @patch("researchhub.views.views.render_to_string")
    def test_robots_txt_view(self, mock_render):
        # Arrange
        mock_render.return_value = "User-agent: *\nDisallow: /admin/"

        # Act
        response = self.client.get(reverse("robots_txt"))

        # Assert
        mock_render.assert_called_once_with("robots.txt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain")
        self.assertEqual(
            response.content.decode("utf-8"), "User-agent: *\nDisallow: /admin/"
        )
