class Error(Exception):
    """Base class for exceptions in this module."""
    pass


class LoginError(Error):
    """Raised for errors related to user login.

    Attributes:
        trigger -- error that triggered this one
        message -- explanation of this error
    """

    def __init__(self, trigger, message):
        self.trigger = trigger
        self.message = message
