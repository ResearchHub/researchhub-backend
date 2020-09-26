from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import Thread, Reply, Comment
from utils.siftscience import events_api


def recalc_dis_count(instance):
    paper = instance.paper
    new_dis_count = paper.get_discussion_count()
    paper.calculate_hot_score()

    if paper.discussion_count < new_dis_count:
        for hub in paper.hubs.all():
            hub.discussion_count += 1
            hub.save()

    paper.discussion_count = new_dis_count
    paper.save()


@receiver(post_save, sender=Thread, dispatch_uid='thread_post_save_signal')
def thread_post_save_signal(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    recalc_dis_count_thread(instance)
    # if created:
    #     events_api.track_create_content_comment(
    #         instance.created_by,
    #         instance,
    #         is_thread=True
    #     )
    # else:
    #     events_api.track_update_content_comment(
    #         instance.created_by,
    #         instance,
    #         is_thread=True
    #     )


def recalc_dis_count_thread(instance):
    recalc_dis_count(instance)


@receiver(post_save, sender=Reply, dispatch_uid='reply_post_save_signal')
def reply_post_save_signal(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    recalc_dis_count_reply(instance)
    # if created:
    #     events_api.track_create_content_comment(
    #         instance.created_by,
    #         instance,
    #     )
    # else:
    #     events_api.track_update_content_comment(
    #         instance.created_by,
    #         instance,
    #     )


def recalc_dis_count_reply(instance):
    recalc_dis_count(instance)


@receiver(post_save, sender=Comment, dispatch_uid='comment_post_save_signal')
def comment_post_save_signal(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    recalc_dis_count_comment(instance)
    # if created:
    #     events_api.track_create_content_comment(
    #         instance.created_by,
    #         instance,
    #     )
    # else:
    #     events_api.track_update_content_comment(
    #         instance.created_by,
    #         instance,
    #     )


def recalc_dis_count_comment(instance):
    recalc_dis_count(instance)


@receiver(post_delete, sender=Thread, dispatch_uid='recalc_dis_count_del_thr')
def recalc_dis_count_thread_delete(sender, instance, **kwargs):
    recalc_dis_count(instance)


@receiver(post_delete, sender=Reply, dispatch_uid='recalc_dis_count_del_reply')
def recalc_dis_count_reply_delete(sender, instance, **kwargs):
    recalc_dis_count(instance)


@receiver(post_delete, sender=Comment, dispatch_uid='recalc_dis_count_del_com')
def recalc_dis_count_comment_delete(sender, instance, **kwargs):
    recalc_dis_count(instance)
