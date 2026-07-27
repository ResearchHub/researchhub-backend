from django.core.exceptions import ObjectDoesNotExist
from django.core.files.storage import default_storage
from django.db.models import Count, F, Prefetch

from analytics.models import UserInteractions
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument


def _preview_image_url(document) -> str | None:
    if document is None:
        return None
    preview_img = getattr(document, "preview_img", None)
    if preview_img:
        return preview_img
    image = getattr(document, "image", None)
    if image:
        return default_storage.url(image)
    return None


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

    document_ids = [
        row["document_id"] for row in top_documents if row["document_id"] is not None
    ]
    unified_docs = {
        doc.id: doc
        for doc in ResearchhubUnifiedDocument.objects.filter(id__in=document_ids)
        .select_related("paper")
        .prefetch_related(
            Prefetch("posts", queryset=ResearchhubPost.objects.order_by("id")),
        )
    }

    for row in top_documents:
        unified_doc = unified_docs.get(row["document_id"])
        if unified_doc is None:
            row["slug"] = ""
            row["preview_img"] = None
            continue

        try:
            document = unified_doc.get_document()
        except (ObjectDoesNotExist, ValueError):
            document = None

        row["slug"] = getattr(document, "slug", "") or ""
        row["preview_img"] = _preview_image_url(document)

    return {"top_documents": top_documents}
