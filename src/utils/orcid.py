import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from django.conf import settings
from django.contrib.sites.models import Site

from utils.retryable_requests import retryable_requests_session

logger = logging.getLogger(__name__)

# Cache settings
_orcid_config = None


def _config():
    global _orcid_config
    if _orcid_config is None:
        _orcid_config = {
            "client_id": getattr(settings, "ORCID_CLIENT_ID"),
            "client_secret": getattr(settings, "ORCID_CLIENT_SECRET"),
            "base_url": getattr(settings, "ORCID_BASE_URL", "https://orcid.org"),
            "api_url": getattr(settings, "ORCID_API_BASE_URL", "https://pub.orcid.org"),
            "redirect_url": getattr(settings, "ORCID_REDIRECT_URL"),
        }
    return _orcid_config


def ensure_orcid_app_configured() -> SocialApp:
    config = _config()
    if not config["client_id"] or not config["client_secret"]:
        raise RuntimeError(
            "ORCID service is not properly configured. Please contact support."
        )

    app, created = SocialApp.objects.get_or_create(
        provider="orcid",
        defaults={
            "name": "ORCID",
            "client_id": config["client_id"],
            "secret": config["client_secret"],
        },
    )

    if not created and (
        app.client_id != config["client_id"] or app.secret != config["client_secret"]
    ):
        SocialApp.objects.filter(id=app.id).update(
            client_id=config["client_id"], secret=config["client_secret"]
        )
        app.refresh_from_db()

    if not app.sites.filter(id=Site.objects.get_current().id).exists():
        app.sites.add(Site.objects.get_current())
    return app


def exchange_orcid_code_for_tokens(code: str) -> Dict:
    config = _config()
    with retryable_requests_session() as session:
        r = session.post(
            f"{config['base_url']}/oauth/token",
            data={
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": config["redirect_url"],
            },
            timeout=30,
        )
    r.raise_for_status()
    return r.json()


def refresh_orcid_access_token(
    account: SocialAccount, token: SocialToken
) -> Optional[SocialToken]:
    if not token.token_secret:
        return None

    config = _config()
    with retryable_requests_session() as session:
        r = session.post(
            f"{config['base_url']}/oauth/token",
            data={
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "grant_type": "refresh_token",
                "refresh_token": token.token_secret,
            },
            timeout=30,
        )

    if r.status_code >= 400:
        return None

    payload = r.json()
    expires_at = None
    if expires_in := payload.get("expires_in"):
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))

    SocialToken.objects.filter(id=token.id).update(
        token=payload.get("access_token"), expires_at=expires_at
    )
    token.refresh_from_db()
    return token


def create_or_update_orcid_account(
    user, token_payload: Dict
) -> Tuple[SocialAccount, SocialToken]:
    orcid_id = token_payload.get("orcid")
    if not orcid_id:
        raise ValueError("ORCID authorization is incomplete. Please try again.")

    # Check for conflicts
    existing = SocialAccount.objects.filter(provider="orcid", uid=orcid_id).first()
    if existing and existing.user_id != user.id:
        raise ValueError(
            f"ORCID ID {orcid_id} is already linked to another user account. "
            f"Each ORCID can only be linked to one ResearchHub account."
        )

    # Upsert account
    account, _ = SocialAccount.objects.update_or_create(
        user=user,
        provider="orcid",
        uid=orcid_id,
        defaults={
            "extra_data": {
                "name": token_payload.get("name"),
                "scope": token_payload.get("scope"),
            }
        },
    )

    # Upsert token
    app = ensure_orcid_app_configured()
    expires_at = None
    if expires_in := token_payload.get("expires_in"):
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))

    token, _ = SocialToken.objects.update_or_create(
        app=app,
        account=account,
        defaults={
            "token": token_payload.get("access_token"),
            "token_secret": token_payload.get("refresh_token"),
            "expires_at": expires_at,
        },
    )

    return account, token


def get_user_orcid_credentials(
    user, auto_refresh: bool = True
) -> Tuple[Optional[SocialAccount], Optional[SocialToken]]:
    try:
        account = SocialAccount.objects.get(user=user, provider="orcid")
        app = ensure_orcid_app_configured()
        token = SocialToken.objects.get(account=account, app=app)

        # Auto-refresh if needed
        if (
            auto_refresh
            and token.expires_at
            and token.expires_at <= datetime.now(timezone.utc)
        ):
            token = refresh_orcid_access_token(account, token)

        return account, token
    except (SocialAccount.DoesNotExist, SocialToken.DoesNotExist):
        return None, None


def fetch_orcid_works_list(access_token: str, orcid_id: str) -> Dict:
    if not access_token or len(access_token) < 10:
        raise ValueError(
            "ORCID access token is invalid. Please reconnect your ORCID account."
        )

    config = _config()
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.orcid+json",
    }

    with retryable_requests_session() as session:
        # Test token validity
        test_r = session.get(
            f"{config['api_url']}/v3.0/{orcid_id}", headers=headers, timeout=30
        )
        if test_r.status_code != 200:
            raise ValueError(
                "Your ORCID access token has expired. "
                "Please reconnect your ORCID account."
            )

        # Fetch works
        r = session.get(
            f"{config['api_url']}/v3.0/{orcid_id}/works", headers=headers, timeout=30
        )

    r.raise_for_status()

    try:
        response_data = r.json()
        if isinstance(response_data, dict) and "group" in response_data:
            logger.info(
                f"Found {len(response_data.get('group', []))} work groups "
                f"in ORCID response"
            )
        return response_data
    except ValueError:
        logger.error(f"ORCID API returned non-JSON response. Status: {r.status_code}")
        raise ValueError(
            "ORCID service returned an invalid response. Please try again later."
        )


def fetch_orcid_work_details(access_token: str, orcid_id: str, put_code: int) -> Dict:
    config = _config()
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.orcid+json",
    }

    with retryable_requests_session() as session:
        url = f"{config['api_url']}/v3.0/{orcid_id}/work/{put_code}"
        r = session.get(url, headers=headers, timeout=30)
    r.raise_for_status()

    try:
        return r.json()
    except ValueError:
        logger.error(
            f"ORCID work detail API returned non-JSON response. "
            f"Status: {r.status_code}"
        )
        raise ValueError(
            "ORCID service returned an invalid response. Please try again later."
        )


def extract_work_identifiers(work_detail: Dict) -> Dict[str, List[str]]:
    out = {}
    for e in work_detail.get("external-ids", {}).get("external-id", []):
        if (typ := (e.get("external-id-type") or "").lower()) and (
            val := e.get("external-id-value")
        ):
            out.setdefault(typ, []).append(val)
    return out


def extract_work_metadata(work_detail: Dict) -> Tuple[Optional[str], Optional[str]]:
    title = None
    if title_data := work_detail.get("title"):
        if isinstance(title_data, dict):
            title = title_data.get("title", {}).get("value") or title_data.get(
                "subtitle", {}
            ).get("value")

    abstract = work_detail.get("short-description") or work_detail.get(
        "abstract", {}
    ).get("value")

    return title, abstract


def get_user_publication_dois(access_token: str, orcid_id: str) -> List[Dict]:
    data = fetch_orcid_works_list(access_token, orcid_id)
    results = []

    for group in data.get("group", []):
        for work_summary in group.get("work-summary", []):
            if not (put_code := work_summary.get("put-code")):
                continue

            try:
                detail = fetch_orcid_work_details(access_token, orcid_id, put_code)
                dois = extract_work_identifiers(detail).get("doi", [])

                if not dois:
                    continue

                title, abstract = extract_work_metadata(detail)
                url = (
                    detail.get("url", {}).get("value")
                    if isinstance(detail.get("url"), dict)
                    else None
                )

                for doi in dois:
                    if doi:
                        results.append(
                            {
                                "doi": doi.lower(),
                                "title": title,
                                "abstract": abstract,
                                "orcid_put_code": put_code,
                                "url": url,
                            }
                        )
            except Exception as e:
                logger.warning(
                    f"Failed to fetch ORCID work detail for put_code {put_code}: {e}"
                )
                continue

    # Deduplicate by DOI
    return list({r["doi"]: r for r in results}.values())
