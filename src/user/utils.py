from utils.sentry import log_error


def merge_author_profiles(source, target):
    # Remap papers
    for paper in source.authored_papers.all():
        paper.authors.remove(source)
        paper.authors.add(target)
        paper.save()

    if target.user and source.user:
        target.user = source.user

    attributes = [
        'first_name',
        'last_name',
        'description',
        'profile_image',
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
            source_val = getattr(source, attr)
            setattr(target, attr, source_val)
        except Exception as e:
            print(e)
            log_error(e)

    target.save()
    source.user = None
    source.orcid_account = None
    source.save()
    return target
