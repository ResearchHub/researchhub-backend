
from django.db.models.signals import post_save
from django.dispatch import receiver

from discussion.reaction_models import Vote
from paper.models import Paper
from researchhub_document.models import (
    ResearchhubUnifiedDocument, ResearchhubPost
)
from researchhub_document.related_models.constants.document_type import (
    PAPER as PaperDocType
)


# Ensures that scores are sync-ed when either is updated
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
    sender=ResearchhubPost,
    dispatch_uid='rh_unified_doc_sync_scores_post_post',
)
@receiver(
    post_save,
    sender=Vote,
    dispatch_uid='rh_unified_doc_sync_scores_post_vote',
)
def rh_unified_doc_sync_scores_post(instance, sender, **kwargs):
    if (
      (sender is ResearchhubPost and instance.unified_document is not None)
      or
      (sender is Vote
          and type(instance.item) is ResearchhubPost
          and (instance.item.unified_document) is not None)
    ):
        print("HOW ABOUT HERE?")
        target_post = instance if sender is ResearchhubPost else instance.item
        target_uni_doc = target_post.unified_document
        sync_scores_uni_doc_and_post(target_uni_doc, target_post)


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


def sync_scores_uni_doc_and_post(unified_doc, post):
    should_save = False
    score = post.calculate_score()  # refer to AbstractGenericReactionModel
    hot_score = post.calculate_hot_score()
    if (unified_doc.hot_score != hot_score):
        unified_doc.hot_score = hot_score
        should_save = True
    if (unified_doc.score != score):
        unified_doc.score = score
        should_save = True
    if (should_save):
        unified_doc.save()
