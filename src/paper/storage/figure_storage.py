from researchhub.storage import SafeS3Storage


class FigureStorage(SafeS3Storage):
    """
    Custom storage class for figure images that uses CloudFront URLs
    instead of presigned S3 URLs.
    """

    querystring_auth = False
