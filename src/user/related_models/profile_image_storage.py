from storages.backends.s3boto3 import S3Boto3Storage


class ProfileImageStorage(S3Boto3Storage):
    def __init__(self):
        super(ProfileImageStorage, self).__init__()

    def url(self, name):
        if 'http' in name:
            return name
        else:
            return super(ProfileImageStorage, self).url(name)
