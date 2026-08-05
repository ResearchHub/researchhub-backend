from allauth.socialaccount.models import SocialApp
from allauth.socialaccount.providers.orcid.provider import OrcidProvider

from utils.cors import is_allowed_origin


def get_orcid_app() -> SocialApp:
    """Get the ORCID social app configuration."""
    return SocialApp.objects.get(provider=OrcidProvider.id)


def is_valid_redirect_url(url: str | None) -> bool:
    """Validate redirect URL against CORS whitelist."""
    return is_allowed_origin(url)
