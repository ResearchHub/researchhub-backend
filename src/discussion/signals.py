from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import Thread, Reply, Comment


@receiver(post_save, sender=Thread, dispatch_uid='thread_post_save_signal')
def thread_post_save_signal(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    paper = instance.paper
    instance.update_discussion_count()
    paper.reset_cache()


@receiver(post_delete, sender=Thread, dispatch_uid='recalc_dis_count_del_thr')
def recalc_dis_count_thread_delete(sender, instance, **kwargs):
    paper = instance.paper
    instance.update_discussion_count()
    paper.reset_cache()


@receiver(post_save, sender=Comment, dispatch_uid='comment_post_save_signal')
def comment_post_save_signal(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    paper = instance.paper
    instance.update_discussion_count()
    paper.reset_cache()


@receiver(post_delete, sender=Comment, dispatch_uid='recalc_dis_count_del_com')
def recalc_dis_count_comment_delete(sender, instance, **kwargs):
    paper = instance.paper
    instance.update_discussion_count()
    paper.reset_cache()


@receiver(post_save, sender=Reply, dispatch_uid='reply_post_save_signal')
def reply_post_save_signal(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    paper = instance.paper
    instance.update_discussion_count()
    paper.reset_cache()

# TODO remove these, discussion should never be deleted?
@receiver(post_delete, sender=Reply, dispatch_uid='recalc_dis_count_del_reply')
def recalc_dis_count_reply_delete(sender, instance, **kwargs):
    paper = instance.paper
    instance.update_discussion_count()
    paper.reset_cache()
