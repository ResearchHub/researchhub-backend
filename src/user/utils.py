from utils.sentry import log_error


def merge_author_profiles(source, target):
    # Remap papers
    for paper in target.authored_papers.all():
        paper.authors.remove(target)
        paper.authors.add(source)
        paper.save()

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
            setattr(source, attr, target_val)
        except Exception as e:
            print(e)
            log_error(e)

    source.save()
    target.user = None
    target.orcid_account = None
    target.save()
    return source
