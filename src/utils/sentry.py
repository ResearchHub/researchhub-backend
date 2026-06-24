import traceback
from warnings import deprecated

from sentry_sdk import (
    capture_exception,
    get_isolation_scope,
)


@deprecated("Use logging instead")
def log_error(e, base_error=None, message=None, json_data=None):
    """Captures an exception with the sentry sdk.

    Arguments:
        e (Exception)
        base_error (Exception) -- Exception that triggered e
        message (str) -- Optional message for additional info
        json_data (dict) -- Optional json data to send with the error
    """
    from researchhub.settings import PRODUCTION

    if not PRODUCTION:
        if isinstance(e, Exception):
            print(e, base_error, message)  # noqa
            try:
                traceback.print_exception(e)
            except Exception:
                pass
        else:
            print(e, base_error, message)  # noqa

    scope = get_isolation_scope()
    if base_error is not None:
        scope.set_extra("base_error", message)
    if message is not None:
        scope.set_extra("message", message)
    if json_data is not None:
        for k, v in json_data.items():
            if isinstance(v, dict):
                for k2, v2 in v.items():
                    scope.set_extra(f"{k}_{k2}", v2)
            elif v is not None:
                scope.set_extra(k, v)
    capture_exception(e)
