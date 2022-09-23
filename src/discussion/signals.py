from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from discussion.models import Comment, Reply, Thread
from notification.models import Notification


@receiver(post_save, sender=Thread, dispatch_uid="create_thread_notifiation")
@receiver(post_save, sender=Comment, dispatch_uid="create_comment_notifiation")
@receiver(post_save, sender=Reply, dispatch_uid="create_reply_notifiation")
def create_thread_notification(sender, instance, created, **kwargs):
    if created:
        creator = instance.created_by
        if isinstance(instance, Thread):
            notification_type = Notification.THREAD_ON_DOC
        elif isinstance(instance, Comment):
            notification_type = Notification.COMMENT_ON_THREAD
        else:
            notification_type = Notification.REPLY_ON_THREAD

        for recipient in instance.users_to_notify:
            if recipient != creator:
                Notification.objects.create(
                    item=instance,
                    unified_document=instance.unified_document,
                    notification_type=notification_type,
                    recipient=recipient,
                    action_user=creator,
                )


@receiver(post_save, sender=Thread, dispatch_uid="thread_post_save_signal")
def thread_post_save_signal(sender, instance, created, update_fields, **kwargs):
    paper = instance.paper
    instance.update_discussion_count()
    if paper:
        paper.reset_cache()


@receiver(post_delete, sender=Thread, dispatch_uid="recalc_dis_count_del_thr")
def recalc_dis_count_thread_delete(sender, instance, **kwargs):
    paper = instance.paper
    instance.update_discussion_count()
    if paper:
        paper.reset_cache()


@receiver(post_save, sender=Comment, dispatch_uid="comment_post_save_signal")
def comment_post_save_signal(sender, instance, created, update_fields, **kwargs):
    paper = instance.paper
    instance.update_discussion_count()
    if paper:
        paper.reset_cache()


@receiver(post_delete, sender=Comment, dispatch_uid="recalc_dis_count_del_com")
def recalc_dis_count_comment_delete(sender, instance, **kwargs):
    paper = instance.paper
    instance.update_discussion_count()
    if paper:
        paper.reset_cache()


@receiver(post_save, sender=Reply, dispatch_uid="reply_post_save_signal")
def reply_post_save_signal(sender, instance, created, update_fields, **kwargs):
    paper = instance.paper
    instance.update_discussion_count()
    if paper:
        paper.reset_cache()
