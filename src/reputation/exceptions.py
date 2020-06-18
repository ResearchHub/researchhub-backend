class Error(Exception):
    """Base class for exceptions in this module."""
    pass


class ReputationDistributorError(Error):
    """Raised for errors related to `distributor` module in the `reputation`
    app.

    Attributes:
        trigger -- error that triggered this one
        message -- explanation of this error
    """

    def __init__(self, trigger, message):
        self.trigger = trigger
        self.message = message


class ReputationSignalError(Error):
    """Raised for errors related to signals in the `reputation` app.

    Attributes:
        trigger -- error that triggered this one
        message -- explanation of this error
    """

    def __init__(self, trigger, message):
        self.trigger = trigger
        self.message = message


class WithdrawalError(Error):
    """Raised for errors related to withdrawal.

    Attributes:
        trigger -- error that triggered this one
        message -- explanation of this error
    """

    def __init__(self, trigger, message):
        self.trigger = trigger
        self.message = message
