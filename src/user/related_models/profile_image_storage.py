from researchhub.storage import SafeS3Storage


class ProfileImageStorage(SafeS3Storage):
    def __init__(self):
        super().__init__()

    def url(self, name):
        if "http" in name:
            return name
        else:
            return super().url(name)
