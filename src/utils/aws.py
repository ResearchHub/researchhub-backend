import hashlib
import json
from datetime import datetime
from urllib.parse import urlparse

from boto3.session import Session
from django.core.files.storage import default_storage
from django.utils.text import slugify

from paper.utils import get_pdf_from_url
from researchhub.settings import (
    AWS_ACCESS_KEY_ID,
    GHOSTSCRIPT_LAMBDA_ARN,
    AWS_S3_REGION_NAME,
    AWS_SECRET_ACCESS_KEY,
    AWS_STORAGE_BUCKET_NAME,
)
from utils.http import check_url_contains_pdf
from utils.sentry import log_error


def get_s3_object_name(key):
    parts = key.split("/")
    return parts[-1]


def get_s3_url(bucket, key, with_credentials=False):
    s3 = "s3://"
    if with_credentials is True:
        return f"{s3}{AWS_ACCESS_KEY_ID}:{AWS_SECRET_ACCESS_KEY}@{bucket}{key}"
    return f"{s3}{bucket}{key}"


def http_to_s3(url, with_credentials=False):
    parsed = urlparse(url)
    bucket = parsed.netloc.split(".", maxsplit=1)[0]
    key = parsed.path

    return get_s3_url(bucket, key, with_credentials=with_credentials)


def upload_to_s3(data, folder):
    ALLOWED_EXTENSIONS = ["pdf"]
    content_type = data.content_type.split("/")[1]

    # Extension check
    if content_type.lower() not in ALLOWED_EXTENSIONS:
        return {"message": "Invalid extension", "status": 400}

    # Special characters check
    if any(not c.isalnum() for c in content_type):
        return {"message": "Special Characters", "status": 400}

    # Filename cleanup
    filename = data.name.split("/")[-1]
    filename = filename.split(".")[0]
    filename = f"{slugify(filename)}.{content_type}"
    content = data.read()
    bucket_directory = f"{folder}/{content_type}"

    if not filename:
        filename = f"{hashlib.md5(content).hexdigest()}.{content_type}"

    path = f"{bucket_directory}/{filename}"
    if default_storage.exists(path):
        url = default_storage.url(path)
    else:
        file_path = default_storage.save(path, data)
        url = default_storage.url(file_path)
    return {
        "url": url.split("?AWSAccessKeyId")[0],
        "full_url": url,
        "filename": filename,
        "path": path,
    }


def lambda_compress_and_linearize_pdf(key, file_name):
    """
    key: path to file in S3 (ex: uploads/tmp/2000/01/01/test.pdf)
    file_name: file name (ex: test.pdf)
    """
    lambda_body = {
        "bucket": AWS_STORAGE_BUCKET_NAME,
        "key": key,
        "file_name": file_name,
    }
    data_bytes = json.dumps(lambda_body)
    session = Session(
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_S3_REGION_NAME,
    )
    lambda_client = session.client(
        service_name="lambda", region_name=AWS_S3_REGION_NAME
    )
    response = lambda_client.invoke(
        FunctionName=GHOSTSCRIPT_LAMBDA_ARN,
        InvocationType="Event",
        Payload=data_bytes,
    )
    return response


def download_pdf(url):
    pdf_url_contains_pdf = check_url_contains_pdf(url)

    if pdf_url_contains_pdf:
        pdf_url = url
        try:
            pdf = get_pdf_from_url(pdf_url)
            pdf.content_type = "application/pdf"
            filename = pdf_url.split("/").pop()
            if not filename.endswith(".pdf"):
                filename += ".pdf"
            pdf.name = filename
            today = datetime.now()
            year = today.strftime("%Y")
            month = today.strftime("%m")
            day = today.strftime("%d")
            folder = f"uploads/citation_entry/attachment/{year}/{month}/{day}"
            s3_data = upload_to_s3(pdf, folder)
            lambda_compress_and_linearize_pdf(s3_data["path"], s3_data["filename"])
            return {"url": s3_data["url"], "signed_url": s3_data["full_url"]}
        except Exception as e:
            print(e)
            log_error(e)
            return None

    return None
