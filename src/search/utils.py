import logging

from django_opensearch_dsl.registries import registry

logger = logging.getLogger(__name__)


def _update_search_index(instance, action):
    """Apply *action* (``"index"`` or ``"delete"``) for a single instance
    across every registered OpenSearch document.

    Calls ``doc.update()`` directly, bypassing signals, Celery, and the
    ``OPENSEARCH_DSL_AUTOSYNC`` gate.
    """
    model = type(instance)
    for doc_class in registry._models.get(model, set()):
        try:
            doc_class().update(instance, action)
        except Exception:
            logger.warning(
                "Search index %s failed for %s id=%s",
                action,
                model.__name__,
                instance.pk,
                exc_info=True,
            )


def remove_from_search_index(instance):
    """Remove a model instance from the OpenSearch index."""
    _update_search_index(instance, "delete")


def bulk_remove_from_search_index(queryset):
    """Remove every instance in *queryset* from the OpenSearch index.

    Intended for use after bulk ``QuerySet.update(is_removed=True)`` calls
    which bypass Django signals.
    """
    for instance in queryset.iterator():
        remove_from_search_index(instance)
