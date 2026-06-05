from utils.sentry import log_error


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
        except Exception as e:
            print(e)
            log_error(e)
