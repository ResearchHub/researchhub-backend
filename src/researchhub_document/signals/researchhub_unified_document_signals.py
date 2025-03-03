from django.db.models.signals import post_save
from django.dispatch import receiver

from discussion.models import Comment, Reply, Thread
from discussion.reaction_models import Vote as GrmVote
from paper.models import Paper
from researchhub_comment.models import RhCommentModel
from researchhub_document.tasks import recalc_hot_score_task
from utils import sentry


@receiver(post_save, sender=GrmVote, dispatch_uid="recalc_hot_score_on_vote")
def recalc_hot_score(instance, sender, **kwargs):
    try:
        recalc_hot_score_task.apply_async(
            (
                instance.content_type_id,
                instance.object_id,
            ),
            priority=2,
            countdown=5,
        )
    except Exception as error:
        print("recalc_hot_score error", error)
        sentry.log_error(error)


# @receiver(post_save, sender=Bounty, dispatch_uid="recalc_hot_score_on_bounty")
# def recalc_hot_score_on_bounty_save(instance, sender, **kwargs):
#     uni_doc = instance.unified_document
#     doc = uni_doc.get_document()
#     content_type = ContentType.objects.get_for_model(doc)

#     try:
#         recalc_hot_score_task.apply_async(
#             (
#                 content_type.id,
#                 doc.id,
#             ),
#             priority=4,
#             countdown=5,
#         )
#     except Exception as error:
#         print("recalc_hot_score on bounty save error", error)
#         sentry.log_error(error)


@receiver(
    post_save,
    sender=Paper,
    dispatch_uid="sync_is_removed_from_paper",
)
def sync_is_removed_from_paper(instance, **kwargs):
    try:
        uni_doc = instance.unified_document
        if uni_doc is not None:
            uni_doc.is_removed = instance.is_removed
            uni_doc.save()
    except Exception:
        return None
