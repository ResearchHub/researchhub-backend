from django.test import TestCase

from paper.models import Paper
from paper.related_models.citation_model import Citation


class CitationTest(TestCase):
    def test_citation_count_no_entry(self):
        paper = Paper.objects.create()
        citation_count = Citation.citation_count(paper=paper)
        self.assertEqual(citation_count, 0)
