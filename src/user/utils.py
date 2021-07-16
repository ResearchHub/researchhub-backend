from utils.sentry import log_error
from user.tasks import preload_latest_activity


def merge_author_profiles(source, target):
    # Remap papers
    for paper in target.authored_papers.all():
        paper.authors.remove(target)
        paper.authors.add(source)
        paper.save()
        paper.reset_cache()

    attributes = [
        'description',
        'author_score',
        'university',
        'orcid_id',
        'orcid_account',
        'education',
        'headline',
        'facebook',
        'linkedin',
        'twitter',
        'academic_verification'
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
    # logical ordering
    target.user = None
    target.orcid_account = None
    target.orcid_id = None
    target.save()
    source.save()
    return source


def reset_latest_acitvity_cache(hub_ids='', ordering='-created_date'):
    preload_latest_activity.apply_async(
        (hub_ids, ordering),
        priority=3
    )
