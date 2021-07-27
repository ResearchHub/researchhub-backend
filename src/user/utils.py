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


def reset_latest_acitvity_cache(
    hub_ids='',
    ordering='-created_date',
    include_default=True,
    use_celery=True
):
    # Resets the 'all' feed
    if include_default:
        if use_celery:
            preload_latest_activity.apply_async(
                ('', ordering),
                priority=3
            )
        else:
            preload_latest_activity('', ordering)

    hub_ids_list = hub_ids.split(',')
    for hub_id in hub_ids_list:
        if use_celery:
            preload_latest_activity.apply_async(
                (hub_id, ordering),
                priority=3
            )
        else:
            preload_latest_activity(hub_id, ordering)
