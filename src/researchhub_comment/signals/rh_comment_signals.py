from django.db.models.signals import post_save
from django.dispatch import receiver

from researchhub_comment.models import RhCommentThreadModel
from discussion.models import Comment, Reply, Thread

@receiver(post_save, sender=Comment, dispatch_uid='from_legacy_comment_to_rh_comment')
def from_legacy_comment_to_rh_comment():
    RhCommentThreadModel
    #  implement


@receiver(post_save, sender=Reply, dispatch_uid='from_legacy_reply_to_rh_comment')
def from_legacy_reply_to_rh_comment():
    RhCommentThreadModel
    #  implement


@receiver(post_save, sender=Comment, dispatch_uid='from_legacy_thread_to_rh_comment')
def from_legacy_thread_to_rh_comment():
    RhCommentThreadModel
    #  implement 