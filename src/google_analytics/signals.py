from django.db.models.signals import post_save
from django.dispatch import receiver

from bullet_point.models import BulletPoint
from discussion.models import Comment, Reply, Thread, Vote as DiscussionVote
from google_analytics.apps import GoogleAnalytics, Hit
from researchhub.settings import PRODUCTION
from paper.models import Paper, Vote as PaperVote
from user.models import User

ga = GoogleAnalytics()


@receiver(
    post_save,
    sender=BulletPoint,
    dispatch_uid='send_bullet_point_event'
)
def send_bullet_point_event(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    category = 'Key Takeaway'
    if instance.bullet_type == BulletPoint.BULLETPOINT_LIMITATION:
        category = 'Limitation'

    label = category

    return get_event_hit_response(
        instance,
        created,
        category,
        label
    )


@receiver(post_save, sender=Comment, dispatch_uid='send_comment_event')
@receiver(post_save, sender=Reply, dispatch_uid='send_comment_event')
@receiver(post_save, sender=Thread, dispatch_uid='send_thread_event')
def send_discussion_event(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    category = 'Discussion'

    label = type(instance).__name__

    return get_event_hit_response(
        instance,
        created,
        category,
        label
    )


@receiver(post_save, sender=Paper, dispatch_uid='send_paper_event')
def send_paper_event(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    if created and instance.retrieved_from_external_source is True:
        return

    action = 'Upload'

    label = None

    if not created and update_fields is not None:
        action = 'Update'
        if 'title' in update_fields:
            label = 'Title'
        # TODO: Will m2m appear here?
        elif 'authors' in update_fields:
            label = 'Authors'
        elif 'summary' in update_fields:
            label = 'Summary'
        elif 'file' in update_fields:
            label = 'PDF'
        else:
            return
    else:
        return

    category = type(instance).__name__
    if label is None:
        label = category
    else:
        label = f'{category} {label}'

    value = 0
    if created:
        if instance.uploaded_by is not None:
            value = instance.uploaded_by.id

    paper_id = instance.id

    date = instance.uploaded_date
    if not created:
        date = instance.updated_date

    return get_event_hit_response(
        instance,
        created,
        category,
        label,
        action=action,
        value=value,
        paper_id=paper_id,
        date=date
    )


@receiver(
    post_save,
    sender=User,
    dispatch_uid='send_user_event'
)
def send_user_event(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    # TODO: Do we want to get new events only and handle updates differently?
    category = 'User'

    action = 'Sign Up'
    label = 'New'
    if not created:
        action = 'Updated'
        label = 'Existing'

    value = instance.id

    return get_event_hit_response(
        instance,
        created,
        category,
        label,
        action=action,
        value=value
    )


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
    category = 'Vote'

    action = 'Upvote'
    if instance.vote_type == 2:
        action = 'Downvote'

    label = 'Paper'
    paper_id = None
    if hasattr(instance, 'item'):
        label = type(instance.item).__name__
        if type(instance.item) is Paper:
            paper_id = instance.item.id
        elif instance.item.paper is not None:
            paper_id = instance.item.paper.id

    return get_event_hit_response(
        instance,
        created,
        category,
        label,
        action=action,
        paper_id=paper_id
    )


def get_event_hit_response(
    instance,
    created,
    category,
    label,
    action=None,
    value=None,
    paper_id=None,
    date=None
):
    if date is None:
        date = instance.created_date
        if not created:
            date = instance.updated_date

    if action is None:
        action = 'Add'
        if not created:
            action = 'Update'

    if (
        (paper_id is None)
        and hasattr(instance, 'paper')
        and (instance.paper is not None)
    ):
        paper_id = instance.paper.id

    label = f'{action} {label}'
    if paper_id is not None:
        label += f' Paper:{paper_id}'

    if (value is None) and (instance.created_by is not None):
        value = instance.created_by.id

    if not PRODUCTION:
        category = 'Test ' + category

    fields = Hit.build_event_fields(
        category=category,
        action=action,
        label=label,
        value=value
    )
    hit = Hit(Hit.EVENT, date, fields)
    return ga.send_hit(hit)
