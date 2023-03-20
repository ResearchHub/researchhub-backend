"""
Mostly handles sending google analytics events on past save signals.

Notice events related to pdf uploads are *not* included here and are better
handled at the view level.
"""
import datetime

from django.db.models.signals import post_save
from django.dispatch import receiver

from bullet_point.models import BulletPoint
from discussion.models import BaseComment, Comment, Reply, Thread
from discussion.models import Vote as GrmVote
from google_analytics.apps import GoogleAnalytics, Hit
from hypothesis.models import Citation
from hypothesis.related_models.hypothesis import Hypothesis
from paper.models import Figure, Paper
from researchhub.celery import QUEUE_EXTERNAL_REPORTING, app
from researchhub.settings import PRODUCTION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from summary.models import Summary
from user.models import User

"""
All this is currently disabled via apps.py
"""

ga = GoogleAnalytics()


@receiver(post_save, sender=BulletPoint, dispatch_uid="send_bullet_point_event")
def send_bullet_point_event(sender, instance, created, update_fields, **kwargs):
    if (not created) or (instance.created_by is None):
        return

    category = "Key Takeaway"
    if instance.bullet_type == BulletPoint.BULLETPOINT_LIMITATION:
        category = "Limitation"

    label = category

    if instance.created_location == BulletPoint.CREATED_LOCATION_PROGRESS:
        label += " from Progress"

    return get_event_hit_response(instance, created, category, label)


@receiver(post_save, sender=Comment, dispatch_uid="send_comment_event")
@receiver(post_save, sender=Reply, dispatch_uid="send_comment_event")
@receiver(post_save, sender=Thread, dispatch_uid="send_thread_event")
def send_discussion_event(sender, instance, created, update_fields, **kwargs):
    if (not created) or (instance.created_by is None):
        return

    category = "Discussion"

    label = type(instance).__name__

    if instance.created_location == BaseComment.CREATED_LOCATION_PROGRESS:
        label += " from Progress"

    return get_event_hit_response(instance, created, category, label)


@receiver(post_save, sender=Figure, dispatch_uid="send_figure_event")
def send_figure_event(sender, instance, created, update_fields, **kwargs):
    if (not created) or (instance.created_by is None):
        return

    category = "Figure"
    if instance.figure_type == Figure.PREVIEW:
        category = "Preview"

    label = category

    if instance.created_location == Figure.CREATED_LOCATION_PROGRESS:
        label += " from Progress"

    return get_event_hit_response(instance, created, category, label)


@receiver(post_save, sender=Paper, dispatch_uid="send_paper_event")
def send_paper_event(sender, instance, created, update_fields, **kwargs):
    if (not created) or (instance.uploaded_by is None):
        return

    action = "Upload"

    label = None

    category = type(instance).__name__
    if label is None:
        label = category
    else:
        label = f"{category} {label}"

    user_id = None
    if instance.uploaded_by is not None:
        user_id = instance.uploaded_by.id

    paper_id = instance.id

    date = instance.uploaded_date

    return get_event_hit_response(
        instance,
        created,
        category,
        label,
        action=action,
        user_id=user_id,
        paper_id=paper_id,
        date=date,
    )


@receiver(post_save, sender=Summary, dispatch_uid="send_summary_event")
def send_summary_event(sender, instance, created, update_fields, **kwargs):
    if (not created) or (instance.proposed_by is None):
        return

    category = "Summary"

    label = category

    if instance.created_location == Summary.CREATED_LOCATION_PROGRESS:
        label += " from Progress"

    user_id = instance.proposed_by.id

    return get_event_hit_response(instance, created, category, label, user_id=user_id)


@receiver(post_save, sender=User, dispatch_uid="send_user_event")
def send_user_event(sender, instance, created, update_fields, **kwargs):
    if not created:
        return

    category = "User"

    action = "Sign Up"
    label = "New"

    user_id = instance.id

    return get_event_hit_response(
        instance, created, category, label, action=action, user_id=user_id
    )


@receiver(post_save, sender=GrmVote, dispatch_uid="send_discussion_vote_event")
def send_vote_event(sender, instance, created, update_fields, **kwargs):
    if (not created) or (instance.created_by is None):
        return

    category = "Vote"

    action = "Upvote"
    if instance.vote_type == 2:
        action = "Downvote"
    label = "Paper"
    paper_id = None
    if hasattr(instance, "item"):
        item_type = type(instance.item)
        label = item_type.__name__
        if item_type in [Citation, Hypothesis, ResearchhubPost]:
            # Items here don't need google analytics at the moment
            return
        if item_type is Paper:
            paper_id = instance.item.id
    return get_event_hit_response(
        instance,
        created,
        category,
        label,
        action=action,
        paper_id=paper_id,
        exclude_paper_id=True,
    )


def get_event_hit_response(
    instance,
    created,
    category,
    label,
    action=None,
    user_id=None,
    paper_id=None,
    date=None,
    exclude_paper_id=False,
):
    if date is None:
        date = instance.created_date
        if not created:
            date = instance.updated_date

    if action is None:
        action = "Add"

    if (
        (paper_id is None)
        and hasattr(instance, "paper")
        and (instance.paper is not None)
    ):
        paper_id = instance.paper.id

    label = f"{action} {label}"
    if not exclude_paper_id:
        if paper_id is not None:
            label += f" Paper:{paper_id}"

    if (user_id is None) and (instance.created_by is not None):
        user_id = instance.created_by.id

    label += f" User:{user_id}"

    if not PRODUCTION:
        category = "Test " + category

    celery_get_event_hit_response.apply_async(
        (category, action, label, 0, date.timestamp())
    )
    return True


@app.task(queue=QUEUE_EXTERNAL_REPORTING)
def celery_get_event_hit_response(category, action, label, value, date):
    date = datetime.datetime.fromtimestamp(date)
    fields = Hit.build_event_fields(
        category=category, action=action, label=label, value=0
    )
    hit = Hit(Hit.EVENT, date, fields)
    ga.send_hit(hit)
    return True
