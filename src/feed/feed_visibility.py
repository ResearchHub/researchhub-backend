from django.db.models import Q, QuerySet


def exclude_hidden_from_feed(
    queryset: QuerySet, lookup: str = "unified_document"
) -> QuerySet:
    """Omit documents a moderator has hidden from public feeds.

    Unified documents with no ``document_filter`` (legacy rows) stay visible.
    Only an explicit ``is_excluded_in_feed=True`` is treated as hidden.
    """
    return queryset.filter(
        Q(**{f"{lookup}__document_filter__isnull": True})
        | Q(**{f"{lookup}__document_filter__is_excluded_in_feed": False})
    )
