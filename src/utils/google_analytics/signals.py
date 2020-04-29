from django.db.models.signals import post_save
from django.dispatch import receiver

from bullet_point.models import BulletPoint
from discussion.models import Vote as DiscussionVote
from researchhub.settings import PRODUCTION
from paper.models import Paper, Vote as PaperVote
from utils.google_analytics.measurement import GoogleAnalytics, Hit

ga = GoogleAnalytics()


@receiver(post_save, sender=BulletPoint, dispatch_uid='send_paper_vote_event')
def send_bullet_point_event(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    if not PRODUCTION:
        return

    category = 'Key Takeaway'
    if instance.bullet_type == BulletPoint.BULLETPOINT_LIMITATION:
        category = 'Limitation'

    label = category

    paper_id = None
    if instance.paper is not None:
        paper_id = instance.paper.id

    response = get_event_hit_response(
        instance,
        created,
        category,
        None,
        label,
        paper_id=paper_id
    )
    print(response)


@receiver(post_save, sender=Paper, dispatch_uid='send_paper_event')
def send_paper_event(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    if not PRODUCTION:
        return

    category = type(instance).__name__

    label = category

    paper_id = None
    if type(instance) == Paper:
        paper_id = instance.id

    value = 0
    if instance.uploaded_by is not None:
        value = instance.uploaded_by.id

    response = get_event_hit_response(
        instance,
        created,
        category,
        None,
        label,
        value=value,
        paper_id=paper_id
    )
    print(response)


@receiver(
    post_save,
    sender=DiscussionVote,
    dispatch_uid='send_discussion_vote_event'
)
@receiver(
    post_save,
    sender=PaperVote,
    dispatch_uid='send_paper_vote_event'
)
def send_vote_event(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    # TODO: Do we want to get new events only and handle updates differently?
    if not PRODUCTION:
        return

    category = 'Vote'

    action = 'Upvote'
    if instance.vote_type == 2:
        action = 'Downvote'

    label = type(instance.item).__name__

    paper_id = None
    if type(instance.item) == Paper:
        paper_id = instance.item.id
    elif instance.item.paper is not None:
        paper_id = instance.item.paper.id

    response = get_event_hit_response(
        instance,
        created,
        category,
        action,
        label,
        paper_id=paper_id
    )
    print(response)


def get_event_hit_response(instance, created, category, action, label, value=None, paper_id=None):
    date = instance.created_date
    if not created:
        date = instance.updated_date

    if action is None:
        action = 'Add'
        if not created:
            action = 'Update'

    if (value is None) and (instance.created_by is not None):
        value = instance.created_by.id

    label = f'{action} {label}'
    if paper_id is not None:
        label += f' Paper:{paper_id}'

    fields = Hit.build_event_fields(
        category=category,
        action=action,
        label=label,
        value=value
    )
    hit = Hit(Hit.EVENT, date, fields)
    return ga.send_hit(hit)
