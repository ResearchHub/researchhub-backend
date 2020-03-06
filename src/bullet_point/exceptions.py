class Error(Exception):
    """Base class for exceptions in this module."""
    pass


class BulletPointModelError(Error):
    """Raised for errors related to the `bullet_point` model.

    Attributes:
        trigger -- error that triggered this one
        message -- explanation of this error
    """

    def __init__(self, trigger, message):
        self.trigger = trigger
        self.message = message
