from sentry_sdk import capture_exception, capture_message, configure_scope


def log_error(e, base_error=None, message=None):
    """Captures an exception with the sentry sdk.

    Arguments:
        e (Exception)
        base_error (Exception) -- Exception that triggered e
        message (str) -- Optional message for additional info
    """
    with configure_scope() as scope:
        if base_error is not None:
            scope.set_extra('base_error', message)
        if message is not None:
            scope.set_extra('message', message)
        capture_exception(e)


def log_request_error(response, message, extra=None):
    with configure_scope() as scope:
        if extra:
            for k in extra:
                scope.set_extra(k, extra[k])
        scope.set_extra('req_error', response.reason)
        capture_exception(message)


def log_info(message, error=None):
    """Captures a message with the sentry sdk.

    Arguments:
        message (str)
        error (obj) -- Optional error to send with the message
    """
    with configure_scope() as scope:
        if error is not None:
            scope.set_extra('error', error)
        capture_message(message)
