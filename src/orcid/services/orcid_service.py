from datetime import timedelta
from urllib.parse import urlencode, urlparse

import requests
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.conf import settings
from django.utils import timezone

from utils.signer import decode_signed_value, encode_signed_value

ORCID_BASE_URL = "https://orcid.org"
STATE_MAX_AGE = 600


def is_valid_redirect_url(url):
    if not url:
        return False
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return origin in settings.CORS_ORIGIN_WHITELIST


def get_orcid_app():
    return SocialApp.objects.get(provider=OrcidProvider.id)


def is_orcid_connected(user):
    if not user:
        return False
    return SocialAccount.objects.filter(user=user, provider=OrcidProvider.id).exists()


def decode_state(state):
    return decode_signed_value(state, max_age=STATE_MAX_AGE)


def exchange_code_for_token(app, code):
    response = requests.post(
        f"{ORCID_BASE_URL}/oauth/token",
        headers={"Accept": "application/json"},
        data={
            "client_id": app.client_id,
            "client_secret": app.secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.ORCID_REDIRECT_URL,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def connect_orcid_account(user, token_data, app):
    if "orcid" not in token_data:
        raise ValueError("Invalid ORCID response")

    orcid_id = token_data["orcid"]
    already_linked = (
        SocialAccount.objects
        .filter(provider=OrcidProvider.id, uid=orcid_id)
        .exclude(user=user)
        .exists()
    )
    if already_linked:
        raise ValueError("ORCID already linked to another account")

    extra_data = {
        "name": token_data.get("name", ""),
        "scope": token_data.get("scope", ""),
    }

    account, _ = SocialAccount.objects.update_or_create(
        user=user,
        provider=OrcidProvider.id,
        defaults={"uid": orcid_id, "extra_data": extra_data},
    )

    expires_at = None
    if expires_in := token_data.get("expires_in"):
        expires_at = timezone.now() + timedelta(seconds=expires_in)

    SocialToken.objects.update_or_create(
        account=account,
        app=app,
        defaults={
            "token": token_data.get("access_token", ""),
            "token_secret": token_data.get("refresh_token", ""),
            "expires_at": expires_at,
        },
    )

    if author := getattr(user, "author_profile", None):
        author.orcid_id = f"{ORCID_BASE_URL}/{orcid_id}"
        author.save(update_fields=["orcid_id"])


def build_auth_url(app, user_id, return_url=None):
    state_data = {"user_id": user_id}
    if is_valid_redirect_url(return_url):
        state_data["return_url"] = return_url
    params = {
        "client_id": app.client_id,
        "response_type": "code",
        "scope": "/authenticate",
        "redirect_uri": settings.ORCID_REDIRECT_URL,
        "state": encode_signed_value(state_data),
    }
    return f"{ORCID_BASE_URL}/oauth/authorize?{urlencode(params)}"


def get_redirect_url(error=None, return_url=None):
    base = return_url if is_valid_redirect_url(return_url) else settings.BASE_FRONTEND_URL
    separator = "&" if "?" in base else "?"
    if error:
        return f"{base}{separator}orcid_error={error}"
    return f"{base}{separator}orcid_connected=true"
