from storages.backends.s3boto3 import S3Boto3Storage


class FigureStorage(S3Boto3Storage):
    """
    Custom storage class for figure images that uses CloudFront URLs
    instead of presigned S3 URLs.
    """

    querystring_auth = False
