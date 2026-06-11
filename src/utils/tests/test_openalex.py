import json
import re
import unittest
from pathlib import Path
from unittest.mock import patch

import responses
from django.test import TestCase

from utils.openalex import OpenAlex, Work, normalize_openalex_id

fixtures_dir = Path(__file__).parent


class OpenAlexTests(TestCase):
    def setUp(self):
        with open(fixtures_dir / "work_by_doi.json", "r") as response_body_file:
            self.works_json = json.load(response_body_file)
        with open(
            fixtures_dir / "openalex_with_researchhub_works.json", "r"
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

    @patch.object(OpenAlex, "_get")
    def test_get_author_fetches_author_by_id(self, mock_get):
        # Arrange
        mock_get.return_value = {"id": "https://openalex.org/A123"}

        # Act
        result = OpenAlex().get_author("A123")

        # Assert
        mock_get.assert_called_once_with("authors/A123")
        self.assertEqual(result["id"], "https://openalex.org/A123")


class NormalizeOpenalexIdTests(unittest.TestCase):
    def test_normalize_openalex_id(self):
        # Arrange
        cases = [
            ("https://openalex.org/A123", "A123"),
            ("https://api.openalex.org/authors/A123/", "A123"),
            (" A123 ", "A123"),
            (None, ""),
            ("", ""),
        ]

        for value, expected in cases:
            with self.subTest(value=value):
                # Act
                result = normalize_openalex_id(value)

                # Assert
                self.assertEqual(result, expected)


class WorkTests(unittest.TestCase):
    def test_from_openalex_maps_fields_and_author_position(self):
        # Arrange
        entity = {
            "display_name": "Lead Paper",
            "publication_year": 2024,
            "doi": "https://doi.org/10.1/lead-paper",
            "id": "https://openalex.org/W1",
            "authorships": [
                {"author": {"id": "A123"}, "author_position": "first"},
            ],
        }

        # Act
        work = Work.from_openalex(entity, author_id="https://openalex.org/A123")

        # Assert
        self.assertEqual(work.title, "Lead Paper")
        self.assertEqual(work.year, "2024")
        self.assertEqual(work.source_url, "https://doi.org/10.1/lead-paper")
        self.assertEqual(work.author_position, "first")

    def test_from_openalex_falls_back_to_openalex_url_without_doi(self):
        # Arrange
        entity = {
            "display_name": "Paper",
            "publication_year": 2023,
            "doi": None,
            "id": "https://openalex.org/W2",
        }

        # Act
        work = Work.from_openalex(entity)

        # Assert
        self.assertEqual(work.source_url, "https://openalex.org/W2")
        self.assertIsNone(work.author_position)

    def test_from_openalex_returns_none_for_unusable_entities(self):
        # Arrange: untitled, and titled but without any URL.
        cases = [
            {"display_name": "", "publication_year": 2023, "doi": None},
            {"display_name": "No URL Paper", "publication_year": 2023, "doi": None},
        ]

        for entity in cases:
            with self.subTest(entity=entity):
                # Act
                work = Work.from_openalex(entity, author_id="A123")

                # Assert
                self.assertIsNone(work)

    def test_label_marks_lead_authorship_and_year(self):
        # Arrange
        cases = [
            (Work("Paper", "2024", "u", "first"), "(2024) Paper [first author]"),
            (Work("Paper", "2024", "u", "last"), "(2024) Paper [last author]"),
            (Work("Paper", "2024", "u", "middle"), "(2024) Paper"),
            (Work("Paper", "", "u", None), "Paper"),
        ]

        for work, expected in cases:
            with self.subTest(expected=expected):
                # Act / Assert
                self.assertEqual(work.label, expected)

    def test_year_int_defaults_to_zero_when_undated(self):
        # Arrange / Act / Assert
        self.assertEqual(Work("Paper", "2024", "u").year_int, 2024)
        self.assertEqual(Work("Paper", "", "u").year_int, 0)

    def test_as_dict_round_trips_profile_fields(self):
        # Arrange
        work = Work("Paper", "2024", "https://doi.org/10.1/p", "first")

        # Act / Assert
        self.assertEqual(
            work.as_dict(),
            {
                "title": "Paper",
                "year": "2024",
                "source_url": "https://doi.org/10.1/p",
                "author_position": "first",
            },
        )
