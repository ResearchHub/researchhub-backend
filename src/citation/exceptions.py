from utils.exceptions import Error


class GrobidProcessingError(Error):
    """Raised for errors related to the `email_notifications` view.

    Attributes:
        trigger -- error that triggered this one
        message -- explanation of this error
    """

    def __init__(self, trigger, message):
        self.trigger = trigger
        self.message = message
