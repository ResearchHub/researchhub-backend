import json

import boto3
from boto3.session import Session
from botocore.config import Config
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
    service_name: str,
    region_name: str = settings.AWS_REGION_NAME,
    *,
    config: Config | None = None,
) -> boto3.client:
    """
    Create a boto3 client for the given service.
    """
    session = Session(region_name=region_name)
    if config is not None:
        return session.client(service_name, config=config)
    return session.client(service_name)


def bedrock_runtime_client() -> boto3.client:
    read_timeout = int(getattr(settings, "BEDROCK_RUNTIME_READ_TIMEOUT", 600))
    max_attempts = int(getattr(settings, "BEDROCK_RUNTIME_MAX_ATTEMPTS", 8))
    # Adaptive retries absorb transient throttling: agent runs make many
    # sequential Converse calls, and one ThrottlingException must not kill a
    # long multi-turn run.
    config = Config(
        connect_timeout=60,
        read_timeout=read_timeout,
        retries={"max_attempts": max_attempts, "mode": "adaptive"},
    )
    return create_client("bedrock-runtime", settings.AWS_REGION_NAME, config=config)
