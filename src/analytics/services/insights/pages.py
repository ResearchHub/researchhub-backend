from django.db.models import Count, F

from analytics.models import UserInteractions


def get_page_metrics(period):
    top_documents = list(
        UserInteractions.objects.filter(
            event="PAGE_VIEW",
            event_timestamp__gte=period.start,
            event_timestamp__lt=period.end,
        )
        .values(
            document_id=F("unified_document_id"),
            document_type=F("unified_document__document_type"),
        )
        .annotate(views=Count("id"))
        .order_by("-views", "document_id")[:10]
    )
    return {"top_documents": top_documents}
