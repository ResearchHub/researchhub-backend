import logging

from django_opensearch_dsl.registries import registry

logger = logging.getLogger(__name__)


def sync_search_index(queryset):
    """Sync the OpenSearch index for every instance in *queryset*.

    Use after bulk ``QuerySet.update()`` calls that change ``is_removed``,
    since ``update()`` bypasses Django signals and the search index
    is not automatically updated.
    """
    for instance in queryset.iterator():
        try:
            registry.update(instance)
        except Exception:
            logger.warning(
                "Failed to sync search index for %s id=%s",
                type(instance).__name__,
                instance.pk,
                exc_info=True,
            )
