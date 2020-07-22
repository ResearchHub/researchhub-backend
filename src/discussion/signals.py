from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import Thread, Reply, Comment


def recalc_dis_count(instance):
    paper = instance.paper
    new_dis_count = paper.get_discussion_count()
    paper.calculate_hot_score()
    paper.discussion_count = new_dis_count
    paper.save()


@receiver(post_save, sender=Thread, dispatch_uid='recalc_dis_count_thread')
def recalc_dis_count_thread(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    recalc_dis_count(instance)


@receiver(post_save, sender=Reply, dispatch_uid='recalc_dis_count_reply')
def recalc_dis_count_reply(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    recalc_dis_count(instance)


@receiver(post_save, sender=Comment, dispatch_uid='recalc_dis_count_comment')
def recalc_dis_count_comment(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
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
