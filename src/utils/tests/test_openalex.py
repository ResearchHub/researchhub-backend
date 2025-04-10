import json
import re
from unittest.mock import patch

import responses
from django.test import TestCase

from utils.openalex import OpenAlex


class OpenAlexTests(TestCase):
    def setUp(self):
        with open("./utils/tests/work_by_doi.json", "r") as response_body_file:
            self.works_json = json.load(response_body_file)
        with open(
            "./utils/tests/openalex_with_researchhub_works.json",
            "r",
        ) as content:
            self.works_json_with_researchhub_works = json.load(content)
        self.works_url = re.compile(r"^https://api.openalex.org/works")
        self.method = "GET"
        self.doi = "10.34133/2020/8086309"

    @responses.activate
    def test_get_data_from_doi(self):
        response = responses.Response(
            method=self.method, url=self.works_url, json=self.works_json
        )
        responses.add(response)

        result = OpenAlex().get_data_from_doi(self.doi)

        self.assertEqual("https://openalex.org/W3018513801", result["id"])

    @responses.activate
    def test_get_works_filter_researchhub_doi(self):
        # Arrange
        response = responses.Response(
            method=self.method,
            url=self.works_url,
            json=self.works_json_with_researchhub_works,
        )
        responses.add(response)

        # Act
        works, _ = OpenAlex().get_works(openalex_author_id="openalexAuthorId1")

        # Assert
        self.assertEqual(len(works), 10)
        self.assertFalse(
            any(
                work.get("doi") is not None and "/researchhub." in work.get("doi", "")
                for work in works
            )
        )

    @responses.activate
    def test_get_data_from_doi_with_retry(self):
        response_429 = responses.Response(
            method=self.method, url=self.works_url, status=429
        )
        response_500 = responses.Response(
            method=self.method, url=self.works_url, status=500
        )
        response_ok = responses.Response(
            method=self.method, url=self.works_url, json=self.works_json
        )
        responses.add(response_429)
        responses.add(response_500)
        responses.add(response_ok)

        result = OpenAlex().get_data_from_doi(self.doi)

        self.assertEqual("https://openalex.org/W3018513801", result["id"])

    @patch.object(OpenAlex, "_get")
    def test_get_works_adds_is_core_parameter(self, mock_get):
        """Test that get_works adds the is_core parameter."""
        # Arrange
        mock_response = {"results": [], "meta": {"next_cursor": None}}
        mock_get.return_value = mock_response

        # Act
        OpenAlex().get_works(batch_size=10, core_sources_only=True)

        # Assert
        args, kwargs = mock_get.call_args
        self.assertEqual(args[0], "works")
        # Verify filter parameters
        filter_params = kwargs["filters"]["filter"].split(",")
        self.assertIn("primary_location.source.is_core:true", filter_params)
        # Verify other parameters
        self.assertEqual(kwargs["filters"]["per-page"], 10)
        self.assertEqual(kwargs["filters"]["cursor"], "*")
