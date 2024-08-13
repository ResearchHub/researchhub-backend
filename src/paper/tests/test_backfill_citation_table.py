import json
import os
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase

from paper.models import Citation, Paper
from paper.openalex_util import process_openalex_works
from utils.openalex import OpenAlex


class BackfillCitationTableTest(TestCase):
    @patch.object(OpenAlex, "get_authors")
    def setUp(self, mock_get_authors):
        # Create some test data
        works_file_path = os.path.join(
            settings.BASE_DIR, "paper", "tests", "openalex_works.json"
        )
        with open(works_file_path, "r") as file:
            response = json.load(file)
            self.works = response.get("results")

        authors_file_path = os.path.join(
            settings.BASE_DIR, "paper", "tests", "openalex_authors.json"
        )
        with open(authors_file_path, "r") as file:
            mock_data = json.load(file)
            mock_get_authors.return_value = (mock_data["results"], None)

            process_openalex_works(self.works)

    def test_backfill_citation_table(self):
        call_command("backfill_citation_table")
        call_command("backfill_citation_table")

        self.assertEqual(Citation.objects.count(), Paper.objects.count())

        for paper in Paper.objects.all():
            citation = Citation.objects.get(paper=paper)
            self.assertEqual(citation.total_citation_count, paper.citations)
            if paper.openalex_id:
                self.assertEqual(citation.source, "OpenAlex")
            else:
                self.assertEqual(citation.source, "Legacy")
            self.assertEqual(citation.citation_change, paper.citations)
