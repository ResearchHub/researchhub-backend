from user.aggregates import TenPercentile, TwoPercentile
from user.models import User
from user.tasks import preload_latest_activity
from utils.sentry import log_error


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
