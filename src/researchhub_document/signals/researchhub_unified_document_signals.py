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


@receiver(
    post_save,
    sender=GrmVote,
    dispatch_uid="rh_unified_doc_sync_score_vote",
)
def rh_unified_doc_sync_score_on_related_docs(instance, sender, **kwargs):
    if not isinstance(instance, (GrmVote)):
        return

    unified_document = instance.unified_document
    if unified_document is None:
        return

    document_obj = instance.item
    if isinstance(document_obj, (Comment, Reply, Thread, RhCommentModel)):
        return

    sync_score(unified_document, document_obj)


def sync_score(unified_doc, document_obj):
    should_save = False
    score = document_obj.calculate_score()  # refer to AbstractGenericReactionModel

    if unified_doc.score != score:
        unified_doc.score = score
        should_save = True

    if should_save:
        unified_doc.save(
            update_fields=[
                "score",
            ]
        )
