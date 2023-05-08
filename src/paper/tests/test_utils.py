import json

from django.test import SimpleTestCase
from paper.utils import call_pdf2html_lambda
from unittest import mock


class TestUtilsCallPdf2HtmlLambda(SimpleTestCase):
    @mock.patch("boto3.client")
    def test_calls_lambda(self, mock_boto_client_fn):
        call_pdf2html_lambda(
            "researchhub-paper-dev1",
            "uploads/papers/2023/04/14/09970713.pdf",
            "researchhub-paper-dev1",
            "uploads/papers/2023/04/14/09970713.html",
        )

        # expect the lambda client to be created
        self.assertEqual(mock_boto_client_fn.call_count, 1)
        self.assertEqual(mock_boto_client_fn.call_args.args, ("lambda",))

        # expect the lambda to be invoked
        mock_lambda_client = mock_boto_client_fn.return_value
        self.assertEqual(mock_lambda_client.invoke.call_count, 1)
        self.assertEqual(mock_lambda_client.invoke.call_args.args, ())
        self.assertEqual(
            mock_lambda_client.invoke.call_args.kwargs,
            {
                "FunctionName": "Pdf2HtmlFunction",
                "InvocationType": "RequestResponse",
                "Payload": json.dumps(
                    {
                        "s3_input": {
                            "bucket_name": "researchhub-paper-dev1",
                            "object_key": "uploads/papers/2023/04/14/09970713.pdf",
                        },
                        "s3_output": {
                            "bucket_name": "researchhub-paper-dev1",
                            "object_key": "uploads/papers/2023/04/14/09970713.html",
                        },
                    }
                ),
            },
        )
