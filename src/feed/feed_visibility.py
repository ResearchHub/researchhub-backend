from django.db.models import QuerySet

from feed.models import HiddenFeedEntry


def exclude_hidden_feed_entries(queryset: QuerySet) -> QuerySet:
    """Omit feed entries a moderator has hidden from public feeds."""
    return queryset.exclude(
        unified_document__document_filter__is_excluded_in_feed=True
    ).exclude(id__in=HiddenFeedEntry.objects.values("feed_entry_id"))
