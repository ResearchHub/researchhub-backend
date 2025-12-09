import json

import boto3
from boto3.session import Session
from django.conf import settings


def lambda_compress_and_linearize_pdf(key, file_name):
    """
    key: path to file in S3 (ex: uploads/tmp/2000/01/01/test.pdf)
    file_name: file name (ex: test.pdf)
    """
    lambda_body = {
        "bucket": settings.AWS_STORAGE_BUCKET_NAME,
        "key": key,
        "file_name": file_name,
    }
    data_bytes = json.dumps(lambda_body)
    lambda_client = create_client("lambda")
    response = lambda_client.invoke(
        FunctionName=settings.GHOSTSCRIPT_LAMBDA_ARN,
        InvocationType="Event",
        Payload=data_bytes,
    )
    return response


def create_client(
    service_name: str, region_name: str = settings.AWS_REGION_NAME
) -> boto3.client:
    """
    Create a boto3 client for the given service.
    """
    session = Session(region_name=region_name)
    return session.client(service_name)
