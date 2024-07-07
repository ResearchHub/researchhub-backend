from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Case, When

import utils.sentry as sentry
from paper.openalex_util import merge_openalex_author_with_researchhub_author
from user.aggregates import TenPercentile, TwoPercentile
from user.models import Organization, User
from user.related_models.author_model import Author
from user.tasks import preload_latest_activity
from user.views.author_views import AuthorClaimException
from utils.openalex import OpenAlex
from utils.sentry import log_error


def claim_author_profile(self, claiming_rh_author_id, openalex_author_id):
    openalex_api = OpenAlex()

    response, cursor = openalex_api.get_authors(openalex_ids=[openalex_author_id])
    openalex_author = response[0]

    if not openalex_author:
        raise Exception("OpenAlex author not found")

    rh_author_with_this_openalex_id = Author.objects.get(
        openalex_ids__contains=[openalex_author_id]
    )
    claiming_rh_author = Author.objects.get(id=claiming_rh_author_id)

    if claiming_rh_author_id == rh_author_with_this_openalex_id.id:
        raise AuthorClaimException(AuthorClaimException.ALREADY_CLAIMED_BY_CURRENT_USER)
    if (
        claiming_rh_author_id != rh_author_with_this_openalex_id.id
        and rh_author_with_this_openalex_id.user is not None
    ):
        raise AuthorClaimException(AuthorClaimException.ALREADY_CLAIMED_BY_ANOTHER_USER)
    elif (
        rh_author_with_this_openalex_id and rh_author_with_this_openalex_id.user is None
    ):
        # An author profile already exists but unclaimed by anyone
        merge_openalex_author_with_researchhub_author(
            openalex_author, claiming_rh_author
        )

        rh_author_with_this_openalex_id.merged_with_author_id = claiming_rh_author_id
        rh_author_with_this_openalex_id.save()
    else:
        merge_openalex_author_with_researchhub_author(
            openalex_author, claiming_rh_author
        )

    claim_author_profile.refresh_from_db()
    return claim_author_profile


def move_paper_to_author(target_paper, target_author, source_author=None):
    target_paper.authors.add(target_author)
    if source_author is not None:
        target_paper.authors.remove(source_author)

    target_paper.save()
    # Commenting out paper cache
    # target_paper.reset_cache()


def merge_author_profiles(source, target):
    # Remap papers
    for paper in target.authored_papers.all():
        print(paper.title)
        paper.authors.remove(target)
        paper.authors.add(source)
        paper.save()
        paper.reset_cache()

    attributes = [
        "description",
        "author_score",
        "university",
        "orcid_id",
        "orcid_account",
        "education",
        "headline",
        "facebook",
        "linkedin",
        "twitter",
        "google_scholar",
        "academic_verification",
    ]
    for attr in attributes:
        try:
            target_val = getattr(target, attr)
            source_val = getattr(source, attr)
            if not source_val:
                setattr(source, attr, target_val)
        except Exception as e:
            print(e)
            log_error(e)

    target.merged_with = source
    # logical ordering
    target.user = None
    target.orcid_account = None
    target.orcid_id = None
    target.claimed = True
    target.save()
    source.save()
    return source


def calculate_show_referral(user):
    aggregation = User.objects.all().aggregate(TenPercentile("reputation"))
    percentage = aggregation["reputation__ten-percentile"]
    reputation = user.reputation
    show_referral = float(reputation) >= percentage
    return show_referral


def calculate_eligible_enhanced_upvotes(user):
    aggregation = User.objects.all().aggregate(TwoPercentile("reputation"))
    percentage = aggregation["reputation__two-percentile"]
    reputation = user.reputation
    eligible = float(reputation) >= percentage
    return eligible


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
