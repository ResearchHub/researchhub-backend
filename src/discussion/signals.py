from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Thread, Reply, Comment


def recalc_dis_count(instance):
    paper = instance.paper
    new_dis_count = paper.get_discussion_count()
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
