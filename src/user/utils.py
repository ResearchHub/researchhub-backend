from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Case, When

from paper.openalex_util import merge_openalex_author_with_researchhub_author
from user.models import Organization
from user.tasks import preload_latest_activity
from utils.openalex import OpenAlex


class AuthorClaimException(Exception):
    ALREADY_CLAIMED_BY_CURRENT_USER = "ALREADY_CLAIMED_BY_CURRENT_USER"
    ALREADY_CLAIMED_BY_ANOTHER_USER = "ALREADY_CLAIMED_BY_ANOTHER_USER"

    def __init__(self, reason):
        self.reason = reason
        self.message = f"Cannot claim author profile: {reason}"
        super().__init__(self.message)


def claim_openalex_author_profile(claiming_rh_author_id, openalex_author_id):
    from user.related_models.author_model import Author
    from user.views.author_views import AuthorClaimException

    if "openalex.org" not in openalex_author_id:
        raise Exception("Invalid OpenAlex author ID")

    openalex_api = OpenAlex()

    response, _ = openalex_api.get_authors(openalex_ids=[openalex_author_id])
    openalex_author = response[0]

    if not openalex_author:
        raise Exception("OpenAlex author not found")

    claiming_rh_author = Author.objects.get(id=claiming_rh_author_id)

    rh_authors_with_this_openalex_id = Author.objects.filter(
        openalex_ids__contains=[openalex_author_id]
    )

    # This will hold a list of authors that can be merged with the claiming author
    mergeable_authors = []
    for rh_author_with_this_openalex_id in rh_authors_with_this_openalex_id:
        already_claimed_by_this_user = (
            claiming_rh_author_id == rh_author_with_this_openalex_id.id
        )
        already_claimed_by_another_user = (
            claiming_rh_author_id != rh_author_with_this_openalex_id.id
            and rh_author_with_this_openalex_id.user is not None
        )

        print("already_claimed_by_this_user", already_claimed_by_this_user)
        print(
            "rh_author_with_this_openalex_id.user", rh_author_with_this_openalex_id.user
        )

        if already_claimed_by_this_user:
            raise AuthorClaimException(
                AuthorClaimException.ALREADY_CLAIMED_BY_CURRENT_USER
            )
        elif already_claimed_by_another_user:
            raise AuthorClaimException(
                AuthorClaimException.ALREADY_CLAIMED_BY_ANOTHER_USER
            )
        else:
            mergeable_authors.append(rh_author_with_this_openalex_id)

    for mergable_author in mergeable_authors:
        mergable_author.merged_with_author_id = claiming_rh_author
        mergable_author.save()

    merge_openalex_author_with_researchhub_author(openalex_author, claiming_rh_author)

    return claiming_rh_author


def reset_latest_acitvity_cache(
    hub_ids="", ordering="-created_date", include_default=True, use_celery=True
):
    # Resets the 'all' feed
    if include_default:
        if use_celery:
            preload_latest_activity.apply_async(("", ordering), priority=1)
        else:
            preload_latest_activity("", ordering)

    hub_ids_list = hub_ids.split(",")
    for hub_id in hub_ids_list:
        if use_celery:
            preload_latest_activity.apply_async((hub_id, ordering), priority=1)
        else:
            preload_latest_activity(hub_id, ordering)


def get_user_organizations(user):
    """Get all organizations which user has access to"""

    org_content_type = ContentType.objects.get_for_model(Organization)
    organization_ids = (
        user.permissions.annotate(
            org_id=Case(
                When(content_type=org_content_type, then="object_id"),
                When(
                    uni_doc_source__note__organization__isnull=False,
                    then="uni_doc_source__note__organization",
                ),
                output_field=models.PositiveIntegerField(),
            )
        )
        .filter(org_id__isnull=False)
        .values("org_id")
    )

    organizations = Organization.objects.filter(id__in=organization_ids)
    return organizations
