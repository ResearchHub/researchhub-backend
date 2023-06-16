import hashlib
from urllib.parse import urlparse

from django.core.files.storage import default_storage
from django.utils.text import slugify

from researchhub.settings import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY


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
    url = url.split("?AWSAccessKeyId")[0]
    return url
