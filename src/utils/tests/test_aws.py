from django.test import TestCase

from utils.aws import http_to_s3


class AWSUtilsTests(TestCase):

    def setUp(self):
        self.bucket = 'researchhub-paper-prod'
        self.key = '/uploads/papers/2019/12/05/858589.full.pdf'
        self.https_pdf_url = (
            f'https://{self.bucket}.s3.us-west-2.amazonaws.com{self.key}'
        )

    def test_http_to_s3(self):
        result = http_to_s3(self.https_pdf_url)
        expected = f's3://{self.bucket}{self.key}'
        self.assertEqual(result, expected)
