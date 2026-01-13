import json
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase

from paper.models import Paper
from paper.openalex_util import process_openalex_works
from paper.related_models.citation_model import Citation
from utils.openalex import OpenAlex

fixtures_dir = Path(__file__).parent / "fixtures"


class CitationTest(TestCase):
    @patch.object(OpenAlex, "get_authors")
    def test_citation_count(self, mock_get_authors):
        with open(fixtures_dir / "openalex_works.json", "r") as file:
            response = json.load(file)
            self.works = response.get("results")

        with open(fixtures_dir / "openalex_authors.json", "r") as file:
            mock_data = json.load(file)
            mock_get_authors.return_value = (mock_data["results"], None)

            process_openalex_works(self.works)

        citations = Citation.objects.all()
        self.assertEqual(citations.count(), 2)

        for paper in Paper.objects.all():
            citation_count = Citation.citation_count(paper)
            self.assertEqual(citation_count, paper.citations)

    def test_citation_count_no_entry(self):
        paper = Paper.objects.create()
        citation_count = Citation.citation_count(paper=paper)
        self.assertEqual(citation_count, 0)
