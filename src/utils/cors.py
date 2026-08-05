import re
from urllib.parse import urlparse

from django.conf import settings


def is_allowed_origin(url: str | None) -> bool:
    """Validate a URL origin against the configured CORS allowlists."""
    if not url:
        return False

    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    if origin in settings.CORS_ORIGIN_WHITELIST:
        return True

    return any(
        re.match(pattern, origin) for pattern in settings.CORS_ALLOWED_ORIGIN_REGEXES
    )
