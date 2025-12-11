import logging
import requests
from urllib.parse import urlencode

from allauth.socialaccount.models import SocialAccount, SocialApp
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.conf import settings
from django.core.cache import cache
from django.db.models import Q

from paper.models import Paper
from paper.openalex_util import process_openalex_works
from paper.related_models.authorship_model import Authorship
from user.related_models.author_model import Author
from utils.openalex import OpenAlex

logger = logging.getLogger(__name__)

ORCID_BASE_URL = "https://orcid.org"
ORCID_API_URL = "https://pub.orcid.org/v3.0"


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
        timeout=30,
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

    try:
        author = user.author_profile
        author.orcid_id = f"{ORCID_BASE_URL}/{orcid_id}"
        author.save(update_fields=["orcid_id"])
    except AttributeError:
        logger.warning(f"User {user.id} connected ORCID but has no author profile")


def build_auth_url(app, user_id):
    params = {
        "client_id": app.client_id,
        "response_type": "code",
        "scope": "/authenticate",
        "redirect_uri": settings.ORCID_REDIRECT_URL,
        "state": str(user_id),
    }
    return f"{ORCID_BASE_URL}/oauth/authorize?{urlencode(params)}"


def extract_orcid_id(orcid_url):
    if not orcid_url:
        return None
    return orcid_url.replace(f"{ORCID_BASE_URL}/", "").strip("/")


def fetch_orcid_works(orcid_id):
    response = requests.get(
        f"{ORCID_API_URL}/{orcid_id}/works",
        headers={"Accept": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def extract_dois_from_orcid_works(orcid_data):
    dois = []
    for group in orcid_data.get("group", []):
        for summary in group.get("work-summary", []):
            for ext_id in summary.get("external-ids", {}).get("external-id", []):
                if ext_id.get("external-id-type") == "doi":
                    doi = ext_id.get("external-id-value")
                    if doi:
                        dois.append(doi)
                    break
    return dois


def sync_orcid_papers(author_id):
    author = Author.objects.get(id=author_id)
    orcid_id = extract_orcid_id(author.orcid_id)

    if not orcid_id:
        raise ValueError("Author has no ORCID connected")

    orcid_data = fetch_orcid_works(orcid_id)
    dois = extract_dois_from_orcid_works(orcid_data)

    if not dois:
        return {"papers_processed": 0, "author_id": author_id}

    openalex = OpenAlex()
    works = []
    for doi in dois:
        work = openalex.get_work_by_doi(doi)
        if work:
            works.append(work)

    if works:
        process_openalex_works(works)

    linked_count = link_papers_to_author(author, works)
    return {"papers_processed": linked_count, "author_id": author_id}


def get_author_position_from_work(work, orcid_id):
    for authorship in work.get("authorships", []):
        author_data = authorship.get("author", {})
        if author_data.get("orcid") == f"{ORCID_BASE_URL}/{orcid_id}":
            return authorship.get("author_position", Authorship.MIDDLE_AUTHOR_POSITION)
    return Authorship.MIDDLE_AUTHOR_POSITION


def link_papers_to_author(author, works):
    orcid_id = extract_orcid_id(author.orcid_id)
    linked = 0

    for work in works:
        raw_doi = work.get("doi", "")
        if not raw_doi:
            continue

        clean_doi = raw_doi.replace("https://doi.org/", "")
        paper = Paper.objects.filter(
            Q(doi__iexact=raw_doi) | Q(doi__iexact=clean_doi)
        ).first()
        if not paper:
            continue

        position = get_author_position_from_work(work, orcid_id)

        _, created = Authorship.objects.get_or_create(
            paper=paper,
            author=author,
            defaults={"author_position": position},
        )
        if created:
            linked += 1

    if linked > 0:
        cache.delete(f"author-{author.id}-publications")

    return linked

