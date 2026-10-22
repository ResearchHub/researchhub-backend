import base64
import json
from unittest import TestCase

import httpx

from research_ai.services.openrouter_image_client import (
    OpenRouterImageClient,
    OpenRouterImageError,
)


def _client(handler) -> OpenRouterImageClient:
    return OpenRouterImageClient(
        "or-test-key", http=httpx.Client(transport=httpx.MockTransport(handler))
    )


class OpenRouterImageClientTests(TestCase):
    def test_posts_the_prompt_and_returns_the_image_bytes(self):
        # Arrange
        requests = []

        def handler(request):
            requests.append(request)
            image = base64.b64encode(b"image-bytes").decode()
            return httpx.Response(200, json={"data": [{"b64_json": image}]})

        # Act
        image = _client(handler).generate(
            model="openai/gpt-image-2.5-sunburst",
            prompt="A banner",
            aspect_ratio="21:9",
            quality="medium",
        )

        # Assert
        self.assertEqual(image, b"image-bytes")
        self.assertEqual(str(requests[0].url), OpenRouterImageClient.URL)
        self.assertEqual(requests[0].headers["Authorization"], "Bearer or-test-key")
        self.assertEqual(
            json.loads(requests[0].content),
            {
                "model": "openai/gpt-image-2.5-sunburst",
                "prompt": "A banner",
                "n": 1,
                "aspect_ratio": "21:9",
                "quality": "medium",
            },
        )

    def test_sends_reference_images(self):
        # Arrange
        bodies = []

        def handler(request):
            bodies.append(json.loads(request.content))
            image = base64.b64encode(b"image-bytes").decode()
            return httpx.Response(200, json={"data": [{"b64_json": image}]})

        # Act
        _client(handler).generate(
            model="m", prompt="p", reference_images=["data:image/png;base64,AAA="]
        )

        # Assert
        self.assertEqual(
            bodies[0]["input_references"],
            [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA="}}],
        )

    def test_an_error_response_raises(self):
        # Arrange
        def handler(request):
            return httpx.Response(402, json={"error": {"message": "No credits"}})

        # Act / Assert
        with self.assertRaises(OpenRouterImageError):
            _client(handler).generate(model="m", prompt="p")

    def test_a_response_without_an_image_raises(self):
        # Arrange
        def handler(request):
            return httpx.Response(200, json={"data": []})

        # Act / Assert
        with self.assertRaises(OpenRouterImageError):
            _client(handler).generate(model="m", prompt="p")
