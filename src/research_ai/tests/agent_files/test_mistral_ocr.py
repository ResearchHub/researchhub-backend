import base64
import json
from unittest import TestCase

import requests
import responses
from django.test import SimpleTestCase, override_settings

from research_ai.services.agent_files.extraction import PageImage
from research_ai.services.agent_files.mistral_ocr import API_URL, MODEL, MistralOcr
from research_ai.services.agent_files.ocr import OcrError

PAGE = PageImage(
    page=3, data=b"\xff\xd8 scanned page", media_type="image/jpeg", width=8, height=8
)


def ocr_response(markdown) -> dict:
    return {
        "pages": [{"index": 0, "markdown": markdown, "images": []}],
        "model": MODEL,
        "usage_info": {"pages_processed": 1},
    }


class MistralOcrTests(TestCase):
    def setUp(self):
        self.ocr = MistralOcr("test-key")

    @responses.activate
    def test_reads_a_page_image_as_markdown(self):
        # Arrange
        responses.post(API_URL, json=ocr_response("# Methods\n\n$E = mc^2$\n"))

        # Act
        text = self.ocr.read_page(PAGE)

        # Assert
        self.assertEqual(text, "# Methods\n\n$E = mc^2$")
        (call,) = responses.calls
        self.assertEqual(call.request.headers["Authorization"], "Bearer test-key")
        body = json.loads(call.request.body)
        self.assertEqual(body["model"], MODEL)
        self.assertEqual(body["document"]["type"], "image_url")
        prefix, _, encoded = body["document"]["image_url"].partition(",")
        self.assertEqual(prefix, "data:image/jpeg;base64")
        self.assertEqual(base64.b64decode(encoded), PAGE.data)

    @responses.activate
    def test_figure_placeholders_are_left_out(self):
        # Arrange
        markdown = "Results\n\n![img-0.jpeg](img-0.jpeg)\n\nFigure 1: Yield by year"
        responses.post(API_URL, json=ocr_response(markdown))

        # Act
        text = self.ocr.read_page(PAGE)

        # Assert
        self.assertEqual(text, "Results\n\nFigure 1: Yield by year")

    @responses.activate
    def test_a_page_holding_only_a_figure_reads_as_empty(self):
        # Arrange
        figures = ["![img-0.jpeg](img-0.jpeg)", "☐ ☐ ☐"]
        for markdown in figures:
            responses.post(API_URL, json=ocr_response(markdown))

        # Act
        texts = [self.ocr.read_page(PAGE) for _ in figures]

        # Assert
        self.assertEqual(texts, ["", ""])

    @responses.activate
    def test_a_rejected_request_is_an_ocr_error(self):
        # Arrange
        responses.post(API_URL, json={"message": "Rate limited"}, status=429)

        # Act / Assert
        with self.assertRaises(OcrError):
            self.ocr.read_page(PAGE)

    @responses.activate
    def test_a_network_failure_is_an_ocr_error(self):
        # Arrange
        responses.post(API_URL, body=requests.ConnectionError("unreachable"))

        # Act / Assert
        with self.assertRaises(OcrError):
            self.ocr.read_page(PAGE)

    @responses.activate
    def test_a_response_without_page_text_is_an_ocr_error(self):
        # Arrange
        bodies = [{"pages": []}, {"pages": [{"index": 0}]}, ocr_response(None), []]
        for body in bodies:
            responses.post(API_URL, json=body)

        # Act / Assert
        for body in bodies:
            with self.subTest(body=body), self.assertRaises(OcrError):
                self.ocr.read_page(PAGE)

    @responses.activate
    def test_a_response_that_is_not_json_is_an_ocr_error(self):
        # Arrange
        responses.post(API_URL, body="<html>Bad gateway</html>")

        # Act / Assert
        with self.assertRaises(OcrError):
            self.ocr.read_page(PAGE)


class MistralOcrFromSettingsTests(SimpleTestCase):
    @override_settings(MISTRAL_API_KEY="")
    def test_there_is_no_engine_without_a_key(self):
        # Act
        ocr = MistralOcr.from_settings()

        # Assert
        self.assertIsNone(ocr)

    @override_settings(MISTRAL_API_KEY="test-key")
    def test_the_engine_uses_the_configured_key(self):
        # Act
        ocr = MistralOcr.from_settings()

        # Assert
        self.assertEqual(ocr.api_key, "test-key")
