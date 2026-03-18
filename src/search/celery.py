import logging

from celery import shared_task
from django.apps import apps
from django.core.cache import cache
from django_opensearch_dsl.registries import registry
from django_opensearch_dsl.signals import RealTimeSignalProcessor
from opensearchpy.helpers import BulkIndexError

import utils.sentry as sentry

logger = logging.getLogger(__name__)

# The debounce period in seconds
DEBOUNCE_PERIOD = 10


class CelerySignalProcessor(RealTimeSignalProcessor):
    def handle_save(self, sender, instance, **kwargs):
        pk = instance.pk
        app_label = instance._meta.app_label
        model = instance._meta.concrete_model
        model_name = model.__name__

        if model in registry._models:
            cache_key = f"registry_update_task_{app_label}_{model_name}_{pk}"
            if not cache.get(cache_key):
                self.registry_update_task.apply_async(
                    (pk, app_label, model_name), countdown=DEBOUNCE_PERIOD
                )
                # Add cache entry to prevent duplicate tasks within debounce period
                cache.set(cache_key, True, timeout=DEBOUNCE_PERIOD)

        if model in registry._related_models:
            cache_key = f"registry_update_related_task_{app_label}_{model_name}_{pk}"
            if not cache.get(cache_key):
                self.registry_update_related_task.apply_async(
                    (pk, app_label, model_name), countdown=DEBOUNCE_PERIOD
                )
                # Add cache entry to prevent duplicate tasks within debounce period
                cache.set(cache_key, True, timeout=DEBOUNCE_PERIOD)

    @shared_task(ignore_result=True)
    def registry_update_task(pk, app_label, model_name):
        try:
            model = apps.get_model(app_label, model_name)
            instance = model.objects.get(pk=pk)
            registry.update(instance)
        except BulkIndexError as e:
            if not _is_benign_bulk_error(e):
                raise
        except LookupError as e:
            sentry.log_error(e)
        except model.DoesNotExist:
            pass

    @shared_task(ignore_result=True)
    def registry_update_related_task(pk, app_label, model_name):
        try:
            model = apps.get_model(app_label, model_name)
            instance = model.objects.get(pk=pk)
            registry.update_related(instance)
        except BulkIndexError as e:
            if not _is_benign_bulk_error(e):
                raise
        except LookupError as e:
            sentry.log_error(e)
        except model.DoesNotExist:
            pass


def _is_benign_bulk_error(exc: BulkIndexError) -> bool:
    """Return True if all failures are delete-not_found (document already absent)."""
    if not hasattr(exc, "errors") or not exc.errors:
        return False
    for item in exc.errors:
        for op_type, op_result in item.items():
            if op_type == "delete" and op_result.get("result") == "not_found":
                continue
            return False
    return True
