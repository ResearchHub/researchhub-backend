
from django.db.models.signals import post_save
from django.dispatch import receiver

from discussion.reaction_models import Vote
from paper.models import Vote as PaperVote
from hypothesis.models import Citation, Hypothesis
from discussion.models import (Thread, Comment, Reply)
from paper.models import Paper
from researchhub_document.models import (
    ResearchhubUnifiedDocument, ResearchhubPost
)
from researchhub_document.related_models.constants.document_type import (
    PAPER as PaperDocType
)
from django.contrib.contenttypes.models import ContentType

@receiver(post_save, sender=Vote, dispatch_uid='recalc_hot_score_on_thread_save')
@receiver(post_save, sender=PaperVote, dispatch_uid='recalc_hot_score_on_thread_save')
def recalc_hot_score(instance, sender, **kwargs):
    uni_doc = None
    if type(instance) is Vote:
        model_name = ContentType.objects.get(id=instance.content_type_id).model
        print('model_name', model_name)
        if model_name == 'hypothesis':
            uni_doc = Hypothesis.objects.get(id=instance.object_id).unified_document
        elif model_name == 'researchhubpost':
            uni_doc = ResearchhubPost.objects.get(id=instance.object_id).unified_document
        elif model_name == 'paper':
            uni_doc = Paper.objects.get(id=instance.object_id).unified_document
        elif model_name in ['thread', 'comment', 'reply']:
            thread = None
            if model_name == 'thread':
                thread = Thread.objects.get(id=instance.object_id)
            elif model_name == 'comment':
                comment = Comment.objects.get(id=instance.object_id)
                thread = comment.parent
            elif model_name == 'reply':
                reply = Reply.objects.get(id=instance.object_id)
                thread = reply.parent.parent

            if thread.paper:
                uni_doc = thread.paper.unified_document
            elif thread.hypothesis:
                uni_doc = thread.hypothesis.unified_document
            elif thread.post:
                uni_doc = thread.post.unified_document
    elif type(instance) is PaperVote:
        uni_doc = instance.paper.unified_document

    if uni_doc:
        uni_doc.calculate_hot_score_v2()

# Ensures that scores are sync-ed when either is updated
# NOTE: we have separate method to sync paper votes because paper has
# its own voting mechanism
@receiver(
    post_save,
    sender=ResearchhubUnifiedDocument,
    dispatch_uid='rh_unified_doc_sync_scores_paper_uni_doc',
)
@receiver(
    post_save,
    sender=Paper,
    dispatch_uid='rh_unified_doc_sync_scores_paper_paper',
)
def rh_unified_doc_sync_scores_paper(instance, sender, **kwargs):
    try:
        if (
            sender is Paper
            and instance.unified_document is not None
        ):
            target_paper = instance
            target_uni_doc = instance.unified_document
        elif (
            sender is ResearchhubUnifiedDocument
            and instance.document_type is PaperDocType
        ):
            target_paper = instance.paper
            target_uni_doc = instance
        else:
            return None
        sync_scores_uni_doc_and_paper(target_uni_doc, target_paper)
    except Exception:
        return None


@receiver(
    post_save,
    sender=Paper,
    dispatch_uid='sync_is_removed_from_paper',
)
def sync_is_removed_from_paper(instance, **kwargs):
    try:
        uni_doc = instance.unified_document
        if (uni_doc is not None):
            uni_doc.is_removed = instance.is_removed
            uni_doc.save()
    except Exception:
        return None


def sync_scores_uni_doc_and_paper(unified_doc, paper):
    should_save = False
    if (unified_doc.hot_score != paper.hot_score):
        unified_doc.hot_score = paper.hot_score
        should_save = True
    if (unified_doc.score != paper.score):
        unified_doc.score = paper.score
        should_save = True
    if (should_save):
        unified_doc.save()


@receiver(
    post_save,
    sender=ResearchhubPost,
    dispatch_uid='rh_unified_doc_sync_post_scores',
)
@receiver(
    post_save,
    sender=Hypothesis,
    dispatch_uid='rh_unified_doc_sync_hypo_scores'
)
@receiver(
    post_save,
    sender=Vote,
    dispatch_uid='rh_unified_doc_sync_scores_vote',
)
def rh_unified_doc_sync_scores_on_related_docs(instance, sender, **kwargs):
    unified_document = instance.unified_document
    if not unified_document:
        return

    if sender is Vote:
        instance = instance.item

    sync_scores(unified_document, instance)


def sync_scores(unified_doc, instance):
    if not type(instance) in (Hypothesis, ResearchhubPost):
        return

    should_save = False
    score = instance.calculate_score()  # refer to AbstractGenericReactionModel
    hot_score = instance.calculate_hot_score()  # AbstractGenericReactionModel
    if unified_doc.hot_score != hot_score:
        unified_doc.hot_score = hot_score
        should_save = True
    if unified_doc.score != score:
        unified_doc.score = score
        should_save = True
    if should_save:
        unified_doc.save()
