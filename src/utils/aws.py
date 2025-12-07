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


def create_bedrock_client(region_name: str = None) -> boto3.client:
    """
    Create a boto3 client for AWS Bedrock Runtime.
    
    Args:
        region_name: AWS region name. Defaults to AWS_BEDROCK_REGION or AWS_REGION_NAME.
    
    Returns:
        boto3 client for bedrock-runtime service
    """
    if region_name is None:
        region_name = getattr(settings, "AWS_BEDROCK_REGION", settings.AWS_REGION_NAME)
    
    return create_client("bedrock-runtime", region_name=region_name)
