import logging

logger = logging.getLogger(__name__)


def update_unified_document_to_paper(paper):
    from researchhub_document.models import ResearchhubUnifiedDocument

    unified_doc = ResearchhubUnifiedDocument.objects.filter(paper__id=paper.id)
    if unified_doc.exists():
        try:
            rh_unified_doc = unified_doc.first()
            curr_score = paper.score
            rh_unified_doc.score = curr_score
            hubs = paper.hubs.all()
            rh_unified_doc.hubs.add(*hubs)
            rh_unified_doc.save()
        except Exception:
            logger.exception("Failed to update unified document to paper %s", paper.id)
