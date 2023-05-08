from django.test import TestCase, tag
from paper.models import Paper
from paper.tasks import celery_pdf2html
from paper.tests.helpers import create_paper

class TestCeleryPdf2Html(TestCase):
    def setUp(self):
        paper = create_paper()
        self.paper_id = paper.id

    def test_returns_false_if_no_paper_id(self):
        result = celery_pdf2html.apply(args=(None,)).get()
        self.assertFalse(result[0])
        self.assertEqual(result[1], 'paper_id is required')

    def test_returns_false_if_paper_does_not_exist(self):
        result = celery_pdf2html.apply(args=(9001,)).get()
        self.assertFalse(result[0])
        self.assertEqual(result[1], 'paper does not exist')

    @tag("aws")
    def test_calls_lambda_functio(self):
        result = celery_pdf2html.apply(args=(self.paper_id,)).get()
        self.assertTrue(result[0])
        