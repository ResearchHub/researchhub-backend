from utils.exceptions import Error


class GrobidProcessingError(Error):
    """Raised for errors related to using the Grobid Service.

    Attributes:
        trigger -- error that triggered this one
        message -- explanation of this error
    """

    def __init__(self, trigger, message):
        self.trigger = trigger
        self.message = message
