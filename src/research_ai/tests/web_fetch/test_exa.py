import json
from unittest import TestCase

import httpx

from research_ai.services.web_fetch.exa import API_URL, ExaContents, FallbackError

URL = "https://www.science.org/doi/10.1126/science.aad5227"


class ExaContentsTests(TestCase):
    def _exa(self, respond):
        self.requests = []

        def handle(request):
            self.requests.append(request)
            return respond

        return ExaContents(
            api_key="exa-key",
            client=httpx.Client(transport=httpx.MockTransport(handle)),
        )

    def test_text_asks_for_one_page_and_returns_its_title_and_text(self):
        # Arrange
        exa = self._exa(
            httpx.Response(
                200,
                json={
                    "results": [
                        {"url": URL, "title": "Gene drives", "text": "Abstract"}
                    ],
                    "statuses": [{"id": URL, "status": "success"}],
                },
            )
        )

        # Act
        title, text = exa.text(URL, max_chars=500, timeout=5)

        # Assert
        (request,) = self.requests
        self.assertEqual(str(request.url), API_URL)
        self.assertEqual(request.headers["x-api-key"], "exa-key")
        self.assertEqual(
            json.loads(request.content),
            {"urls": [URL], "text": {"maxCharacters": 500}, "livecrawlTimeout": 20_000},
        )
        self.assertEqual((title, text), ("Gene drives", "Abstract"))

    def test_text_raises_when_no_page_comes_back(self):
        cases = {
            "HTTP 402": httpx.Response(402, json={"tag": "X402_PAYMENT_REQUIRED"}),
            "CRAWL_NOT_FOUND": httpx.Response(
                200,
                json={
                    "results": [],
                    "statuses": [
                        {
                            "id": URL,
                            "status": "error",
                            "error": {"tag": "CRAWL_NOT_FOUND"},
                        }
                    ],
                },
            ),
            "invalid JSON": httpx.Response(200, json=["not", "an", "object"]),
            "no text": httpx.Response(
                200, json={"results": [{"url": URL, "text": " "}]}
            ),
        }
        for expected, response in cases.items():
            with self.subTest(expected):
                # Arrange
                exa = self._exa(response)

                # Act
                with self.assertRaises(FallbackError) as raised:
                    exa.text(URL, max_chars=500, timeout=5)

                # Assert
                self.assertIn(expected, str(raised.exception))
