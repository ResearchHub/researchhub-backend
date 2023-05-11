from unittest import skip

from django.test import TestCase, tag

from paper.tasks import celery_pdf2html
from paper.tests.helpers import create_paper


# TODO: Fix/add unit tests?
# create_paper does not upload a file to s3
# so this test fails.
# Uploading a file to S3 everytime a test is called is not ideal
# because it adds unnecessary files to S3 that needs to be cleaned up
@skip
class TestCeleryPdf2Html(TestCase):
    def setUp(self):
        paper = create_paper()
        self.paper_id = paper.id

    def test_returns_false_if_no_paper_id(self):
        result = celery_pdf2html.apply(args=(None,)).get()
        self.assertFalse(result[0])
        self.assertEqual(result[1], "paper_id is required")

    def test_returns_false_if_paper_does_not_exist(self):
        result = celery_pdf2html.apply(args=(9001,)).get()
        self.assertFalse(result[0])
        self.assertEqual(result[1], "paper does not exist")

    @tag("aws")
    def test_calls_lambda_function(self):
        result = celery_pdf2html.apply(args=(self.paper_id,)).get()
        self.assertTrue(result[0])
