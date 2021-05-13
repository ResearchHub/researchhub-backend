from urllib.parse import urlparse

from researchhub.settings import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY


def get_s3_url(bucket, key, with_credentials=False):
    s3 = 's3://'
    if with_credentials is True:
        return (
            f'{s3}{AWS_ACCESS_KEY_ID}:{AWS_SECRET_ACCESS_KEY}@{bucket}{key}'
        )
    return f'{s3}{bucket}{key}'


def http_to_s3(url, with_credentials=False):
    parsed = urlparse(url)
    bucket = parsed.netloc.split('.', maxsplit=1)[0]
    key = parsed.path

    return get_s3_url(bucket, key, with_credentials=with_credentials)
