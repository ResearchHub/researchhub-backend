import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from django.conf import settings
from django.contrib.sites.models import Site

from utils.retryable_requests import retryable_requests_session

logger = logging.getLogger(__name__)


def get_orcid_configuration() -> Dict[str, str]:
    return {
        "client_id": getattr(settings, "ORCID_CLIENT_ID"),
        "client_secret": getattr(settings, "ORCID_CLIENT_SECRET"),
        "base_url": getattr(settings, "ORCID_BASE_URL", "https://orcid.org"),
        "api_url": getattr(settings, "ORCID_API_BASE_URL", "https://pub.orcid.org"),
        "redirect_url": getattr(settings, "ORCID_REDIRECT_URL"),
    }


def create_standard_orcid_api_headers(access_token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.orcid+json",
    }


def build_oauth_token_request_payload(
    orcid_config: Dict[str, str], **additional_params
) -> Dict[str, str]:
    base_payload = {
        "client_id": orcid_config["client_id"],
        "client_secret": orcid_config["client_secret"],
    }
    base_payload.update(additional_params)
    return base_payload


def calculate_future_token_expiry_time(expires_in_seconds: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=int(expires_in_seconds))


def execute_orcid_oauth_token_request(url: str, payload: Dict[str, str]) -> Dict:
    with retryable_requests_session() as http_session:
        response = http_session.post(
            url,
            data=payload,
            headers={"Accept": "application/json"},
            timeout=30,
        )
    response.raise_for_status()
    return response.json()


def execute_orcid_api_data_request(url: str, headers: Dict[str, str]) -> Dict:
    with retryable_requests_session() as http_session:
        response = http_session.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    try:
        return response.json()
    except ValueError:
        logger.error(
            f"ORCID API returned non-JSON response. Status: {response.status_code}"
        )
        raise OrcidServiceError()


def extract_publication_title_from_orcid_work_data(work_data: Dict) -> str:
    title_section = work_data.get("title", {})
    if (
        title_section
        and "title" in title_section
        and title_section["title"].get("value")
    ):
        return title_section["title"]["value"]
    return ""


def extract_publication_abstract_from_orcid_work_data(work_data: Dict) -> str:
    if "short-description" in work_data and work_data["short-description"]:
        return work_data["short-description"]
    return ""


def ensure_orcid_django_social_app_exists() -> SocialApp:
    orcid_config = get_orcid_configuration()

    if not orcid_config["client_id"] or not orcid_config["client_secret"]:
        raise RuntimeError(
            "ORCID service is not properly configured. Please contact support."
        )

    orcid_app, app_was_created = SocialApp.objects.get_or_create(
        provider="orcid",
        defaults={
            "name": "ORCID",
            "client_id": orcid_config["client_id"],
            "secret": orcid_config["client_secret"],
        },
    )

    app_needs_configuration_update = not app_was_created and (
        orcid_app.client_id != orcid_config["client_id"]
        or orcid_app.secret != orcid_config["client_secret"]
    )

    if app_needs_configuration_update:
        SocialApp.objects.filter(id=orcid_app.id).update(
            client_id=orcid_config["client_id"], secret=orcid_config["client_secret"]
        )
        orcid_app.refresh_from_db()

    current_site = Site.objects.get_current()
    if not orcid_app.sites.filter(id=current_site.id).exists():
        orcid_app.sites.add(current_site)

    return orcid_app


def exchange_orcid_code_for_tokens(authorization_code: str) -> Dict:
    orcid_config = get_orcid_configuration()

    token_request_payload = build_oauth_token_request_payload(
        orcid_config,
        grant_type="authorization_code",
        redirect_uri=orcid_config["redirect_url"],
        code=authorization_code,
    )

    return execute_orcid_oauth_token_request(
        f"{orcid_config['base_url']}/oauth/token", token_request_payload
    )


def refresh_expired_orcid_access_token(
    orcid_account: SocialAccount, expired_token: SocialToken
) -> Optional[SocialToken]:
    if not expired_token.token_secret:
        return None

    orcid_config = get_orcid_configuration()

    refresh_request_payload = build_oauth_token_request_payload(
        orcid_config,
        grant_type="refresh_token",
        refresh_token=expired_token.token_secret,
    )

    refreshed_token_data = execute_orcid_oauth_token_request(
        f"{orcid_config['base_url']}/oauth/token", refresh_request_payload
    )

    new_access_token = refreshed_token_data.get("access_token")
    token_expires_at = None

    if expires_in_seconds := refreshed_token_data.get("expires_in"):
        token_expires_at = calculate_future_token_expiry_time(expires_in_seconds)

    SocialToken.objects.filter(id=expired_token.id).update(
        token=new_access_token, expires_at=token_expires_at
    )
    expired_token.refresh_from_db()
    return expired_token


def create_or_update_orcid_account(
    user, orcid_token_data: Dict
) -> Tuple[SocialAccount, SocialToken]:
    orcid_user_id = orcid_token_data.get("orcid")
    if not orcid_user_id:
        raise OrcidAuthenticationError()

    existing_orcid_account = SocialAccount.objects.filter(
        provider="orcid", uid=orcid_user_id
    ).first()
    if existing_orcid_account and existing_orcid_account.user_id != user.id:
        raise OrcidAccountConflictError()

    user_orcid_account, _ = SocialAccount.objects.update_or_create(
        user=user,
        provider="orcid",
        uid=orcid_user_id,
        defaults={
            "extra_data": {
                "name": orcid_token_data.get("name"),
                "scope": orcid_token_data.get("scope"),
            }
        },
    )

    orcid_social_app = ensure_orcid_django_social_app_exists()
    token_expires_at = None

    if expires_in_seconds := orcid_token_data.get("expires_in"):
        token_expires_at = calculate_future_token_expiry_time(expires_in_seconds)

    user_orcid_token, _ = SocialToken.objects.update_or_create(
        app=orcid_social_app,
        account=user_orcid_account,
        defaults={
            "token": orcid_token_data.get("access_token"),
            "token_secret": orcid_token_data.get("refresh_token"),
            "expires_at": token_expires_at,
        },
    )

    return user_orcid_account, user_orcid_token


def get_user_orcid_credentials(
    user, auto_refresh: bool = True
) -> Tuple[Optional[SocialAccount], Optional[SocialToken]]:
    try:
        user_orcid_account = SocialAccount.objects.get(user=user, provider="orcid")
        orcid_social_app = ensure_orcid_django_social_app_exists()
        user_orcid_token = SocialToken.objects.get(
            account=user_orcid_account, app=orcid_social_app
        )

        token_is_expired = (
            user_orcid_token.expires_at
            and user_orcid_token.expires_at <= datetime.now(timezone.utc)
        )

        if auto_refresh and token_is_expired:
            user_orcid_token = refresh_expired_orcid_access_token(
                user_orcid_account, user_orcid_token
            )

        return user_orcid_account, user_orcid_token
    except (SocialAccount.DoesNotExist, SocialToken.DoesNotExist):
        return None, None


def fetch_user_works_list_from_orcid_api(access_token: str, orcid_user_id: str) -> Dict:
    if not access_token or len(access_token) < 10:
        raise OrcidTokenExpiredError()

    orcid_config = get_orcid_configuration()
    api_request_headers = create_standard_orcid_api_headers(access_token)

    with retryable_requests_session() as http_session:
        profile_validation_response = http_session.get(
            f"{orcid_config['api_url']}/v3.0/{orcid_user_id}",
            headers=api_request_headers,
            timeout=30,
        )

        if profile_validation_response.status_code != 200:
            raise OrcidTokenExpiredError()

    works_data = execute_orcid_api_data_request(
        f"{orcid_config['api_url']}/v3.0/{orcid_user_id}/works", api_request_headers
    )

    if isinstance(works_data, dict) and "group" in works_data:
        work_group_count = len(works_data.get("group", []))
        logger.info(f"Found {work_group_count} work groups in ORCID response")
    return works_data


def fetch_single_work_details_from_orcid_api(
    access_token: str, orcid_user_id: str, work_put_code: int
) -> Dict:
    orcid_config = get_orcid_configuration()
    api_request_headers = create_standard_orcid_api_headers(access_token)
    work_detail_api_url = (
        f"{orcid_config['api_url']}/v3.0/{orcid_user_id}/work/{work_put_code}"
    )

    return execute_orcid_api_data_request(work_detail_api_url, api_request_headers)


def extract_all_identifiers_from_orcid_work_data(
    orcid_work_detail: Dict,
) -> Dict[str, List[str]]:
    extracted_identifiers = {}
    external_id_list = orcid_work_detail.get("external-ids", {}).get("external-id", [])

    for external_id_entry in external_id_list:
        identifier_type = external_id_entry.get("external-id-type")
        identifier_value = external_id_entry.get("external-id-value")

        if identifier_type and identifier_value:
            if identifier_type not in extracted_identifiers:
                extracted_identifiers[identifier_type] = []
            extracted_identifiers[identifier_type].append(identifier_value)
    return extracted_identifiers


def get_user_publication_dois(access_token: str, orcid_user_id: str) -> List[Dict]:
    user_works_data = fetch_user_works_list_from_orcid_api(access_token, orcid_user_id)
    complete_user_publications_with_dois = []

    work_groups = user_works_data.get("group", [])
    for single_work_group in work_groups:
        work_summaries_in_group = single_work_group.get("work-summary", [])

        for individual_work_summary in work_summaries_in_group:
            work_put_code = individual_work_summary.get("put-code")
            if not work_put_code:
                continue

            try:
                detailed_work_data = fetch_single_work_details_from_orcid_api(
                    access_token, orcid_user_id, work_put_code
                )
                work_identifiers = extract_all_identifiers_from_orcid_work_data(
                    detailed_work_data
                )

                work_dois = work_identifiers.get("doi", [])
                if not work_dois:
                    continue

                work_title = extract_publication_title_from_orcid_work_data(
                    detailed_work_data
                )
                work_abstract = extract_publication_abstract_from_orcid_work_data(
                    detailed_work_data
                )

                for individual_doi in work_dois:
                    publication_record = {
                        "doi": individual_doi,
                        "title": work_title,
                        "abstract": work_abstract,
                        "put_code": work_put_code,
                    }
                    complete_user_publications_with_dois.append(publication_record)

            except Exception as work_processing_error:
                logger.warning(
                    f"Failed to fetch ORCID work {work_put_code}: "
                    f"{work_processing_error}"
                )
                continue
    return complete_user_publications_with_dois


class OrcidAccountConflictError(ValueError):
    pass


class OrcidAuthenticationError(ValueError):
    pass


class OrcidTokenExpiredError(ValueError):
    pass


class OrcidServiceError(ValueError):
    pass
