from urllib.parse import urlparse

from allauth.socialaccount.models import SocialApp
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.conf import settings


def get_orcid_app() -> SocialApp:
    """Get the ORCID social app configuration."""
    return SocialApp.objects.get(provider=OrcidProvider.id)


def is_valid_redirect_url(url: str | None) -> bool:
    """Validate redirect URL against CORS whitelist."""
    if not url:
        return False
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}" in settings.CORS_ORIGIN_WHITELIST
