import requests
from urllib.parse import urlencode

from allauth.socialaccount.models import SocialAccount, SocialApp
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.conf import settings

ORCID_BASE_URL = "https://orcid.org"


def get_orcid_app():
    return SocialApp.objects.get(provider=OrcidProvider.id)


def is_orcid_connected(user):
    if not user:
        return False
    return SocialAccount.objects.filter(user=user, provider=OrcidProvider.id).exists()


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
    )
    response.raise_for_status()
    return response.json()


def connect_orcid_account(user, token_data):
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

    SocialAccount.objects.update_or_create(
        user=user,
        provider=OrcidProvider.id,
        defaults={"uid": orcid_id, "extra_data": token_data},
    )

    if author := getattr(user, "author_profile", None):
        author.orcid_id = f"{ORCID_BASE_URL}/{orcid_id}"
        author.save(update_fields=["orcid_id"])


def build_auth_url(app, user_id):
    params = {
        "client_id": app.client_id,
        "response_type": "code",
        "scope": "/authenticate",
        "redirect_uri": settings.ORCID_REDIRECT_URL,
        "state": str(user_id),
    }
    return f"{ORCID_BASE_URL}/oauth/authorize?{urlencode(params)}"
