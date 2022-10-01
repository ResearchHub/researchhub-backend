import json
import re

import responses

from django.test import TestCase
from utils.openalex import OpenAlex


class OpenAlexTests(TestCase):
    def setUp(self):
        with open("./utils/tests/work_by_doi.json", "r") as response_body_file:
            self.works_json = json.load(response_body_file)
        self.works_url = re.compile(r"^https://api.openalex.org/works")
        self.method = "GET"
        self.doi = "10.34133/2020/8086309"

    @responses.activate
    def test_get_data_from_doi(self):
        response = responses.Response(
            method=self.method,
            url=self.works_url,
            json=self.works_json)
        responses.add(response)

        result = OpenAlex().get_data_from_doi(self.doi)

        self.assertEqual("https://openalex.org/W3018513801", result["id"])


    @responses.activate
    def test_get_data_from_doi_with_retry(self):
        response_429 = responses.Response(
            method=self.method,
            url=self.works_url,
            status=429
        )
        response_500 = responses.Response(
            method=self.method,
            url=self.works_url,
            status=500
        )
        response_ok = responses.Response(
            method=self.method,
            url=self.works_url,
            json=self.works_json)
        responses.add(response_429)
        responses.add(response_500)
        responses.add(response_ok)

        result = OpenAlex().get_data_from_doi(self.doi)

        self.assertEqual("https://openalex.org/W3018513801", result["id"])
