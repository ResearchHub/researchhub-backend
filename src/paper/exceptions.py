
class Error(Exception):
    """Base class for exceptions in this module."""
    pass


class PaperSerializerError(Error):
    """Raised for errors related to `paper` serializers.

    Attributes:
        trigger -- error that triggered this one
        message -- explanation of this error
    """

    def __init__(self, trigger, message):
        self.trigger = trigger
        self.message = message
