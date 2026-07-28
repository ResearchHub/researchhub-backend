from django.core.exceptions import ObjectDoesNotExist
from django.core.files.storage import default_storage
from django.db.models import Count, F, Prefetch

from analytics.models import UserInteractions
from paper.models import Figure
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import PAPER


def _post_preview_image_url(post) -> str | None:
    if post.preview_img:
        return post.preview_img
    if post.image:
        return default_storage.url(post.image)
    return None


def _paper_preview_image_url(paper) -> str | None:
    figure = (
        paper.figures.filter(is_primary=True).first()
        or paper.figures.filter(figure_type=Figure.PREVIEW).first()
    )
    if figure is None:
        return None
    if figure.thumbnail:
        return figure.thumbnail.url
    if figure.file:
        return figure.file.url
    return None


def _preview_image_url(*, document_type: str, document) -> str | None:
    if document is None:
        return None
    if document_type == PAPER:
        return _paper_preview_image_url(document)
    return _post_preview_image_url(document)


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
            "paper__figures",
        )
    }

    for row in top_documents:
        unified_doc = unified_docs.get(row["document_id"])
        if unified_doc is None:
            row.update(
                {
                    "paper_id": None,
                    "post_id": None,
                    "slug": "",
                    "url": None,
                    "preview_img": None,
                }
            )
            continue

        try:
            document = unified_doc.get_document()
            url = unified_doc.frontend_view_link()
        except (ObjectDoesNotExist, ValueError, AttributeError):
            document = None
            url = None

        is_paper = unified_doc.document_type == PAPER
        row["paper_id"] = document.id if document is not None and is_paper else None
        row["post_id"] = document.id if document is not None and not is_paper else None
        row["slug"] = getattr(document, "slug", "") or ""
        row["url"] = url
        row["preview_img"] = _preview_image_url(
            document_type=unified_doc.document_type,
            document=document,
        )

    return {"top_documents": top_documents}
