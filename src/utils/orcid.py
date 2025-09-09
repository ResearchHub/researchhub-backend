# utils/orcid.py
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from django.conf import settings
from django.contrib.sites.models import Site

from utils.retryable_requests import retryable_requests_session

ORCID_PROVIDER = "orcid"
ORCID_BASE_URL = getattr(settings, "ORCID_BASE_URL", "https://orcid.org")
ORCID_API_BASE_URL = getattr(settings, "ORCID_API_BASE_URL", "https://pub.orcid.org")

logger = logging.getLogger(__name__)


def _ensure_orcid_social_app() -> SocialApp:
    """
    Ensure there is a configured Django-Allauth `SocialApp` for ORCID and link it
    to the current `Site`.

    Behavior:
    - Creates the `SocialApp` with client id/secret from settings if missing.
    - Updates stored client id/secret if they differ from settings.
    - Ensures the app is attached to the current `Site` so tokens can be created.

    Raises:
    - RuntimeError: If ORCID client id/secret are not configured in settings.

    Returns:
    - The ensured `SocialApp` instance for provider "orcid".
    """
    client_id = getattr(settings, "ORCID_CLIENT_ID", None)
    client_secret = getattr(settings, "ORCID_CLIENT_SECRET", None)
    if not client_id or not client_secret:
        raise RuntimeError("ORCID client id/secret not configured")

    app, _ = SocialApp.objects.get_or_create(
        provider=ORCID_PROVIDER,
        defaults={"name": "ORCID", "client_id": client_id, "secret": client_secret},
    )
    changed = False
    if app.client_id != client_id:
        app.client_id = client_id
        changed = True
    if app.secret != client_secret:
        app.secret = client_secret
        changed = True
    if changed:
        app.save(update_fields=["client_id", "secret"])

    site = Site.objects.get_current()
    if site not in app.sites.all():
        app.sites.add(site)
    return app


def exchange_code_for_token(code: str) -> Dict:
    """
    Exchange an ORCID authorization code for an access/refresh token pair.

    Args:
    - code: Authorization code obtained from ORCID callback.

    Returns:
    - JSON payload from ORCID containing `access_token`, `refresh_token`,
      `expires_in`, `orcid`, `name`, `scope`, `token_type`.
    """
    data = {
        "client_id": getattr(settings, "ORCID_CLIENT_ID"),
        "client_secret": getattr(settings, "ORCID_CLIENT_SECRET"),
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": getattr(
            settings,
            "ORCID_REDIRECT_URI",
            getattr(settings, "ORCID_REDIRECT_URL", None),
        ),
    }
    with retryable_requests_session() as session:
        r = session.post(f"{ORCID_BASE_URL}/oauth/token", data=data, timeout=30)
    r.raise_for_status()
    return r.json()


def refresh_access_token(
    account: SocialAccount, token: SocialToken
) -> Optional[SocialToken]:
    """
    Refresh an expired ORCID access token using the stored refresh token.

    Args:
    - account: The ORCID `SocialAccount` the token belongs to.
    - token: The existing `SocialToken` (its `token_secret` stores refresh token).

    Returns:
    - Updated `SocialToken` on success, or `None` if refresh fails or missing.
    """
    refresh_token = token.token_secret  # store refresh_token here
    if not refresh_token:
        return None

    data = {
        "client_id": getattr(settings, "ORCID_CLIENT_ID"),
        "client_secret": getattr(settings, "ORCID_CLIENT_SECRET"),
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    with retryable_requests_session() as session:
        r = session.post(f"{ORCID_BASE_URL}/oauth/token", data=data, timeout=30)
    if r.status_code >= 400:
        return None
    payload = r.json()
    token.token = payload.get("access_token")
    expires_in = payload.get("expires_in")
    if expires_in:
        token.expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=int(expires_in)
        )
    token.save(update_fields=["token", "expires_at"])
    return token


def upsert_orcid_token(user, payload: Dict) -> Tuple[SocialAccount, SocialToken]:
    """
    Create or update the user's ORCID `SocialAccount` and `SocialToken`.

    Expected payload keys:
    - access_token, refresh_token, expires_in, orcid, name, scope, token_type

    Behavior:
    - Ensures the ORCID `SocialApp` exists and is linked to the current Site.
    - Upserts the `SocialAccount` identified by `orcid` and the user.
    - Stores access token, refresh token, and expiry in `SocialToken`.
    - Updates account `extra_data` with `name` and `scope` when provided.

    Raises:
    - ValueError: If the payload is missing the `orcid` identifier.

    Returns:
    - A tuple of (`SocialAccount`, `SocialToken`).
    """
    orcid_id = payload.get("orcid")
    if not orcid_id:
        raise ValueError("ORCID token payload missing 'orcid'")

    account, _ = SocialAccount.objects.get_or_create(
        user=user,
        provider=ORCID_PROVIDER,
        uid=orcid_id,
        defaults={
            "extra_data": {"name": payload.get("name"), "scope": payload.get("scope")}
        },
    )
    ed = account.extra_data or {}
    updated = False
    for k in ("name", "scope"):
        v = payload.get(k)
        if v and ed.get(k) != v:
            ed[k] = v
            updated = True
    if updated:
        account.extra_data = ed
        account.save(update_fields=["extra_data"])

    # ✅ Ensure SocialApp exists/attached before creating the SocialToken
    app = _ensure_orcid_social_app()
    token, _ = SocialToken.objects.get_or_create(app=app, account=account)
    token.token = payload.get("access_token")
    token.token_secret = payload.get("refresh_token")  # keep refresh_token here
    expires_in = payload.get("expires_in")
    if expires_in:
        token.expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=int(expires_in)
        )
    token.save()
    return account, token


def get_orcid_account_and_token(
    user, auto_refresh: bool = True
) -> Tuple[Optional[SocialAccount], Optional[SocialToken]]:
    """
    Retrieve the user's ORCID account and token, optionally auto-refreshing.

    Args:
    - user: Django user instance.
    - auto_refresh: If True, refresh the token when it is expired.

    Returns:
    - (`SocialAccount` or None, `SocialToken` or None)
    """
    try:
        account = SocialAccount.objects.get(user=user, provider=ORCID_PROVIDER)
    except SocialAccount.DoesNotExist:
        return None, None
    try:
        # ✅ Ensure SocialApp exists before looking up the token
        app = _ensure_orcid_social_app()
        token = SocialToken.objects.get(account=account, app=app)
    except (SocialApp.DoesNotExist, SocialToken.DoesNotExist):
        return account, None

    if (
        auto_refresh
        and token.expires_at
        and token.expires_at <= datetime.now(timezone.utc)
    ):
        token = refresh_access_token(account, token)
    return account, token


def fetch_works_summary(access_token: str, orcid_id: str) -> Dict:
    """
    Fetch the ORCID 'works' summary listing for an ORCID iD.

    Returns the JSON from `GET /v3.0/{orcid_id}/works`.
    """
    # Validate inputs
    if not access_token or len(access_token) < 10:
        raise ValueError("Invalid access token")

    url = f"{ORCID_API_BASE_URL}/v3.0/{orcid_id}/works"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.orcid+json",  # Use ORCID-specific Accept header
        "Content-Type": "application/vnd.orcid+json",
    }

    with retryable_requests_session() as session:
        # Test basic ORCID record access first
        test_r = session.get(
            f"{ORCID_API_BASE_URL}/v3.0/{orcid_id}", headers=headers, timeout=30
        )
        if test_r.status_code != 200:
            raise ValueError(
                f"Invalid ORCID access token - cannot access record {orcid_id}"
            )

        # Fetch works
        r = session.get(url, headers=headers, timeout=30)

    r.raise_for_status()

    try:
        response_data = r.json()
        if isinstance(response_data, dict) and "group" in response_data:
            logger.info(
                f"Found {len(response_data.get('group', []))} work groups "
                f"in ORCID response"
            )
        return response_data
    except ValueError as e:
        # Handle empty or invalid JSON response
        import re

        # Extract just the HTML title and any error messages
        content_preview = r.text[:200]
        if "html" in r.headers.get("content-type", "").lower():
            # Extract title and body content for HTML responses
            title_match = re.search(
                r"<title[^>]*>([^<]+)</title>", r.text, re.IGNORECASE
            )
            body_match = re.search(
                r"<body[^>]*>(.*?)</body>", r.text, re.IGNORECASE | re.DOTALL
            )

            title = title_match.group(1) if title_match else "No title"
            body_snippet = body_match.group(1)[:300] if body_match else "No body"
            # Remove HTML tags from body snippet
            body_clean = re.sub(r"<[^>]+>", " ", body_snippet).strip()
            content_preview = f"Title: {title} | Body: {body_clean}"

        logger.error(
            f"ORCID API returned non-JSON response. Status: {r.status_code}, "
            f"Content-Type: {r.headers.get('content-type')}"
        )
        logger.error(f"Content: {content_preview}")

        raise ValueError(
            f"Invalid JSON response from ORCID works API: {e}. Status: {r.status_code}"
        )


def fetch_work_detail(access_token: str, orcid_id: str, put_code: int) -> Dict:
    """
    Fetch detailed metadata for a single ORCID work by its put-code.

    Returns the JSON from `GET /v3.0/{orcid_id}/work/{put_code}`.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.orcid+json",
        "Content-Type": "application/vnd.orcid+json",
    }
    with retryable_requests_session() as session:
        r = session.get(
            f"{ORCID_API_BASE_URL}/v3.0/{orcid_id}/work/{put_code}",
            headers=headers,
            timeout=30,
        )
    r.raise_for_status()

    try:
        work_detail = r.json()
        return work_detail
    except ValueError as e:
        # Handle empty or invalid JSON response
        import re

        # Extract just the HTML title and any error messages
        content_preview = r.text[:200]
        if "html" in r.headers.get("content-type", "").lower():
            title_match = re.search(
                r"<title[^>]*>([^<]+)</title>", r.text, re.IGNORECASE
            )
            body_match = re.search(
                r"<body[^>]*>(.*?)</body>", r.text, re.IGNORECASE | re.DOTALL
            )

            title = title_match.group(1) if title_match else "No title"
            body_snippet = body_match.group(1)[:300] if body_match else "No body"
            body_clean = re.sub(r"<[^>]+>", " ", body_snippet).strip()
            content_preview = f"Title: {title} | Body: {body_clean}"

        logger.error(
            f"ORCID work detail API returned non-JSON response. "
            f"Status: {r.status_code}, "
            f"Content-Type: {r.headers.get('content-type')}"
        )
        logger.error(f"Content: {content_preview}")

        raise ValueError(
            f"Invalid JSON response from ORCID work detail API: {e}. "
            f"Status: {r.status_code}"
        )


def extract_external_ids(work_detail: Dict) -> Dict[str, List[str]]:
    """
    Extract external identifiers from an ORCID work detail payload.

    Returns a mapping of identifier type (lowercased) to list of values, e.g.
    `{ "doi": ["10.1234/abc"], "pmid": ["12345"] }`.
    """
    out: Dict[str, List[str]] = {}
    ext_ids = work_detail.get("external-ids", {}).get("external-id", [])
    for e in ext_ids:
        typ = (e.get("external-id-type") or "").lower()
        val = e.get("external-id-value")
        if typ and val:
            out.setdefault(typ, []).append(val)
    return out


def extract_title_abstract(work_detail: Dict) -> Tuple[Optional[str], Optional[str]]:
    """
    Pull a best-effort title and abstract from an ORCID work detail payload.

    Returns:
    - (title, abstract), each possibly `None` if not present.
    """
    title = None
    abstract = None
    if "title" in work_detail:
        t = work_detail["title"]
        if isinstance(t, dict):
            title = t.get("title", {}).get("value") or t.get("subtitle", {}).get(
                "value"
            )
    if "short-description" in work_detail and work_detail["short-description"]:
        abstract = work_detail["short-description"]
    if not abstract:
        ab = work_detail.get("abstract", {})
        if isinstance(ab, dict):
            abstract = ab.get("value")
    return title, abstract


def list_user_dois(access_token: str, orcid_id: str) -> List[Dict]:
    """
    Enumerate DOIs from a user's ORCID works with optional title/abstract/url.

    For each ORCID work in the summary, fetch detail, extract `doi` values and
    enrich with a best-effort `title`, `abstract`, and `url` when present.

    Returns:
    - A list of dicts: { 'doi', 'title', 'abstract', 'orcid_put_code', 'url' }
      with DOIs lowercased and duplicates deduplicated by DOI.
    """
    data = fetch_works_summary(access_token, orcid_id)
    results: List[Dict] = []
    groups = data.get("group", [])
    for g in groups:
        wsum = g.get("work-summary", []) or g.get("work-group", []) or []
        for ws in wsum:
            put_code = ws.get("put-code")
            if put_code is None:
                continue
            detail = fetch_work_detail(access_token, orcid_id, put_code)
            ids_map = extract_external_ids(detail)
            dois = ids_map.get("doi", [])
            url = None
            if isinstance(detail.get("url"), dict):
                url = detail["url"].get("value")
            title, abstract = extract_title_abstract(detail)
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
    dedup = {r["doi"]: r for r in results}
    return list(dedup.values())
